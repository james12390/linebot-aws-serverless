import os
import json
import base64
import hmac
import hashlib
import urllib.request
import urllib.error
import boto3

# ==========================================
# 1. 新增 X-Ray 追蹤初始化
# ==========================================
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.core import patch_all

# 自動補丁：這會讓 boto3 (DynamoDB, Bedrock) 和 urllib (LINE API) 的呼叫自動被紀錄
patch_all()

# --- 告訴 Lambda 東京的筆記本與 AI 大腦在哪 ---
# 1. 取得東京區 DynamoDB 資源
dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
table = dynamodb.Table('LineBotUserData')

# 2. 取得東京區 Bedrock Agent 工具
bedrock_agent = boto3.client(service_name='bedrock-agent-runtime', region_name='ap-northeast-1')

# --- 環境變數設定 ---
CHANNEL_SECRET = os.environ.get("CHANNEL_SECRET", "")
ACCESS_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN", "")
REPLY_ENDPOINT = "https://api.line.me/v2/bot/message/reply"

# --- Agent 資訊 ---
AGENT_ID = 'GZ2Z3OQLS6'
AGENT_ALIAS_ID = 'RZZYF7YJI1'

def _get_header(headers: dict, name: str):
    if not headers:
        return None
    target = name.lower()
    for k, v in headers.items():
        if k.lower() == target:
            return v
    return None

def verify_line_signature(raw_body_bytes: bytes, signature: str) -> bool:
    if not CHANNEL_SECRET or not signature:
        return False
    mac = hmac.new(CHANNEL_SECRET.encode("utf-8"), raw_body_bytes, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature)

# ==========================================
# 2. 加入 X-Ray 裝飾器追蹤 Bedrock 呼叫耗時
# ==========================================
@xray_recorder.capture('get_agent_response')
def get_agent_response(user_text: str, session_id: str):
    """呼叫 Bedrock Agent，它會幫你處理知識庫與 Flow 邏輯"""
    try:
        response = bedrock_agent.invoke_agent(
            agentId=AGENT_ID,
            agentAliasId=AGENT_ALIAS_ID,
            sessionId=session_id,
            inputText=user_text,
            sessionState={
                'sessionAttributes': {
                    'line_user_id': session_id 
                }
            }
        )
        
        full_answer = ""
        event_stream = response.get('completion')
        if event_stream:
            for event in event_stream:
                if 'chunk' in event:
                    full_answer += event['chunk']['bytes'].decode('utf-8')
        
        return full_answer if full_answer else "抱歉，秘書這題沒給出答案。"
        
    except Exception as e:
        print(f"Agent Error: {str(e)}")
        # 將錯誤紀錄到 X-Ray
        xray_recorder.current_subsegment().add_exception(e)
        return f"系統忙碌中，請稍後再試"

# ==========================================
# 3. 加入 X-Ray 裝飾器追蹤 LINE 回傳耗時
# ==========================================
@xray_recorder.capture('reply_line')
def reply_line(reply_token: str, text: str):
    """回傳訊息給你的 LINE Bot"""
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    }
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        REPLY_ENDPOINT,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ACCESS_TOKEN}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            _ = resp.read()
    except Exception as e:
        print("Reply error:", str(e))
        xray_recorder.current_subsegment().add_exception(e)


SKIP_KEYWORDS = ["行程規劃使用規則", "PDF使用規則", "地點詳情查詢規則"]

# ==========================================
# 4. 主程式 Lambda Handler
# ==========================================
def lambda_handler(event, context):
    body_str = event.get("body") or ""
    is_b64 = bool(event.get("isBase64Encoded"))

    if is_b64:
        raw_body_bytes = base64.b64decode(body_str)
    else:
        raw_body_bytes = body_str.encode("utf-8")

    headers = event.get("headers") or {}
    signature = _get_header(headers, "x-line-signature")

    # 驗證訊息是否真的從 LINE 送來
    if not verify_line_signature(raw_body_bytes, signature):
        return {"statusCode": 401, "body": "Invalid signature"}

    payload = json.loads(raw_body_bytes.decode("utf-8"))
    events = payload.get("events", [])
    
    reply = "收到了！但我不太確定您的意思。如果是要規劃行程，請依照格式輸入：\n地區：\n天數：\n人數："
    
    for e in events:
        if e.get("type") == "message" and (e.get("message") or {}).get("type") == "text":
            reply_token = e.get("replyToken")
            user_text = e["message"]["text"]
            user_id = e["source"].get("userId", "default-user")
            
            if user_text in SKIP_KEYWORDS:
                if user_text == "行程規劃使用規則":
                    reply = "請依照格式輸入：\n地區：\n天數：\n人數：\n旅遊風格：\n美食與購物偏好：\n預算範圍\n出發日期\n旅行風格請依照(1)傳統文化（寺廟、神社）(2)現代都市（逛街、美食）(3)自然風景(4)混合型\n美食與購物偏好請依照(1)高級餐廳/米其林(2)大眾美食/街頭小食(3)逛百貨/購物商圈(4)夜生活/酒吧\n以上兩項填數字就行"
                elif user_text == "為您生成PDF中請稍等":
                    user_text == "生成PDF"
                    reply = get_agent_response(user_text, user_id)
                elif user_text == "地點詳情查詢規則":
                    reply = "請輸入 「地點 + 詳細資訊」\n例如：台北車站 詳細資訊\n（請勿只輸入地點）"
                return reply_line(reply_token, reply)

            elif reply_token:
                # 這裡會進入 get_agent_response 的 X-Ray 區塊
                ai_response = get_agent_response(user_text, user_id)
                reply_line(reply_token, ai_response)

    return {"statusCode": 200, "body": "OK"}