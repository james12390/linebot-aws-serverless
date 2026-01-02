import boto3
from datetime import datetime
import json

# 初始化資料庫連線
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("TravelAgentMemory")

def lambda_handler(event, context):
    try:
        # 1. 取得 API 路徑 (例如 /get_memory)
        api_path = event.get('apiPath')
        action_group = event.get('actionGroup')
        
        # 2. 解析 Bedrock 傳進來的參數
        properties = event.get("requestBody", {}).get("content", {}).get("application/json", {}).get("properties", [])
        params = {p["name"]: p["value"] for p in properties}
        
        # 抓取雙鑰匙：userId 和 sessionId
        user_id = params.get("userId")
        session_id = params.get("sessionId")
        
        # 如果沒抓到 userId，回傳錯誤，因為這是開啟門的必要條件
        if not user_id or not session_id:
            raise Exception(f"缺少必要參數！userId: {user_id}, sessionId: {session_id}")

        response_data = {}

        # --- 功能 A：讀取記憶 (需要雙 Key) ---
        if api_path == "/get_memory":
            db_res = table.get_item(
                Key={
                    'userId': user_id,
                    'sessionId': session_id
                }
            )
            item = db_res.get('Item')
            if item:
                # 找到舊病歷了！
                response_data = {
                    "status": "found",
                    "history": item.get("conversation"),
                    "last_updated": item.get("updatedAt")
                }
            else:
                # 沒找到紀錄，視為新客人
                response_data = {"status": "not_found", "message": "這是第一次對話，沒有舊紀錄。"}

        # --- 功能 B：儲存記憶 (存入時也要帶雙 Key) ---
        elif api_path == "/save_memory":
            conversation = params.get("conversation")
            if not conversation:
                raise Exception("想要存記憶，但沒給我 conversation 內容。")

            table.put_item(
                Item={
                    'userId': user_id,
                    'sessionId': session_id,
                    'conversation': conversation,
                    'updatedAt': datetime.now().isoformat()
                }
            )
            response_data = {"status": "success", "message": "記憶已儲存。"}

        # 3. 封裝回傳給 Bedrock 的格式
        return {
            'messageVersion': '1.0',
            'response': {
                'actionGroup': action_group,
                'apiPath': api_path,
                'httpMethod': event.get('httpMethod'),
                'httpStatusCode': 200,
                'responseBody': {
                    'application/json': {
                        'body': json.dumps(response_data, ensure_ascii=False)
                    }
                }
            }
        }

    except Exception as e:
        print(f"❌ 出錯了：{str(e)}")
        return {
            'messageVersion': '1.0',
            'response': {
                'actionGroup': event.get('actionGroup'),
                'httpStatusCode': 500,
                'responseBody': {
                    'application/json': {
                        'body': json.dumps({"error": str(e)}, ensure_ascii=False)
                    }
                }
            }
        }