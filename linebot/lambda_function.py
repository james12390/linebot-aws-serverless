import os
import json
import base64
import hmac
import hashlib
import urllib.request
import urllib.error
import boto3

# --- 新增這段：告訴 Lambda 東京的筆記本與 AI 大腦在哪 ---
# 1. 取得東京區 DynamoDB 資源
dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
table = dynamodb.Table('LineBotUserData')

# 2. 取得東京區 Bedrock Agent 工具
bedrock_agent = boto3.client(service_name='bedrock-agent-runtime', region_name='ap-northeast-1')
# import lambda_GoogleMapsAPI

# --- 環境變數設定 ---
# 這些會從 Lambda 的「組態」->「環境變數」中讀取
CHANNEL_SECRET = os.environ.get("CHANNEL_SECRET", "")
ACCESS_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN", "")
REPLY_ENDPOINT = "https://api.line.me/v2/bot/message/reply"

# --- Agent 資訊 (已幫你填好) ---
AGENT_ID = 'GZ2Z3OQLS6'               # 你的專屬 Agent ID
#AGENT_ALIAS_ID = 'XYSPTJ5ON1'         # 預設測試別名，如果你有自定義 Alias 請更換
AGENT_ALIAS_ID = 'XYSPTJ5ON1'

# 初始化 Bedrock Agent 用戶端
# 根據你的截圖，我們使用的是東京區域 (ap-northeast-1)
bedrock_agent = boto3.client(service_name='bedrock-agent-runtime', region_name='ap-northeast-1')

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

def get_agent_response(user_text: str, session_id: str):
    """呼叫 Bedrock Agent，它會幫你處理知識庫與 Flow 邏輯"""
    try:
        # 這是呼叫秘書的關鍵動作
        response = bedrock_agent.invoke_agent(
            agentId=AGENT_ID,
            agentAliasId=AGENT_ALIAS_ID,
            sessionId=session_id, # 使用者的 ID，讓 AI 能記得前後文
            inputText=user_text,
            # ✨ 關鍵：在這裡設定，PDF Lambda 才拿得到 line_user_id
            sessionState={
                'sessionAttributes': {
                    'line_user_id': session_id 
                }
            }
        )
        
        full_answer = ""
        # 這裡會接收 Agent 回傳的內容碎片並拼湊
        event_stream = response.get('completion')
        if event_stream:
            for event in event_stream:
                if 'chunk' in event:
                    full_answer += event['chunk']['bytes'].decode('utf-8')
        
        return full_answer if full_answer else "抱歉，秘書這題沒給出答案。"
        
    except Exception as e:
        print(f"Agent Error: {str(e)}")
        return f"系統忙碌中，請稍後再試"

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


SKIP_KEYWORDS = ["行程規劃使用規則", "PDF使用規則", "地點詳情查詢規則"]
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
    #頭2025/12/31新增
    #尾2025/12/31新增
    reply = "收到了！但我不太確定您的意思。如果是要規劃行程，請依照格式輸入：\n地區：\n天數：\n人數："
    for e in events:
        if e.get("type") == "message" and (e.get("message") or {}).get("type") == "text":
            reply_token = e.get("replyToken")
            user_text = e["message"]["text"]
            # 用使用者的 userId 當對話 Session，這樣 AI 才會記得他是誰
            user_id = e["source"].get("userId", "default-user")
            if user_text in SKIP_KEYWORDS:
              if user_text == "行程規劃使用規則":
                reply = "請依照格式輸入：\n地區：\n天數：\n人數："
              elif user_text == "PDF使用規則":
                reply = "請先確認行程草案，確認完請說:生成PDF"
              elif user_text == "地點詳情查詢規則":
                reply = "請依照格式輸入：\n地點+詳細資訊\n例:台北車站詳細資訊"
              return reply_line(reply_token,reply)

            elif reply_token:
                ai_response = get_agent_response(user_text, user_id)
                reply_line(reply_token, ai_response)

    return {"statusCode": 200, "body": "OK"}
