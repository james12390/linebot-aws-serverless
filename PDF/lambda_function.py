import json
import boto3
import os
import uuid
import pdfkit
import requests
from jinja2 import Environment, FileSystemLoader
from botocore.config import Config

# 初始化 S3 客戶端
s3_client = boto3.client(
    's3', 
    region_name='ap-northeast-1',
    aws_access_key_id=os.environ.get('MY_AWS_ACCESS_KEY'),
    aws_secret_access_key=os.environ.get('MY_AWS_SECRET_KEY'),
    config=Config(s3={'addressing_style': 'virtual'}) # 強制虛擬託管樣式
)

# S3 Access Point Alias
S3_AP_ALIAS = os.environ.get('S3_AP_ALIAS', 'travel-helper-s3-ap-iz8sxtni358ka78i843d4y4uy9uzkapn1a-s3alias')


def lambda_handler(event, context):
    print(f"DEBUG - Agent Call: {json.dumps(event)}")
    
    # --- 診斷區塊：檢查環境 ---
    bin_path = '/opt/bin/wkhtmltopdf'
    font_path = '/opt/python/lib/python3.12/site-packages/NotoSansTC-Regular.ttf'
    
    check_results = {
        "wkhtmltopdf_exists": os.path.exists(bin_path),
        "font_exists": os.path.exists(font_path),
        "python_path": os.environ.get('PYTHONPATH')
    }
    print(f"環境檢查: {json.dumps(check_results)}")

    try:
        # 1. 提取參數
        parameters = event.get('parameters', [])
        itinerary_raw = next((p['value'] for p in parameters if p['name'] == 'itinerary_content'), None)

        if not itinerary_raw:
            return format_action_response(event, "❌ 錯誤：未接收到行程數據。")

        # 2. 暴力定位 JSON 區塊 (這能過濾掉所有 \n, <tags>, ```json 等雜質)
        start_index = itinerary_raw.find('{')
        end_index = itinerary_raw.rfind('}') + 1
        data = json.loads(itinerary_raw[start_index:end_index], strict=False)

        # 3. 使用 Jinja2 讀取外部 HTML 模板
        # 假設 template.html 放在 Lambda 根目錄
        env = Environment(loader=FileSystemLoader(os.path.dirname(__file__)))
        template = env.get_template('template.html')

        config = pdfkit.configuration(wkhtmltopdf='/opt/bin/wkhtmltopdf')
        options = {
            'encoding': "UTF-8",
            'enable-local-file-access': None,
            'javascript-delay': '2000',       # ✨ 加上這個確保 Icon 抓取更穩定
            'no-stop-slow-scripts': None,
            'quiet': ''
        }
        
        html_out = template.render(
            title=data.get('title', '旅遊行程'),
            style=data.get('style', ''),
            days=data.get('days', []),
            transportation=data.get('transportation', ''),
            budget_info=data.get('budget_info', ''),    # ✨ 關鍵：補上這一行
            reminders=data.get('reminders', '')
        )

        # 4. HTML 轉 PDF (使用 wkhtmltopdf Layer)
        # 注意：wkhtmltopdf 的執行檔路徑需與您的 Layer 一致
        config = pdfkit.configuration(wkhtmltopdf='/opt/bin/wkhtmltopdf')
        options = {
            'encoding': "UTF-8",
            'enable-local-file-access': None,
            'quiet': ''
        }
        pdf_output = pdfkit.from_string(html_out, False, configuration=config, options=options)

        
        # 5. 上傳 S3
        file_key = f"itineraries/{str(uuid.uuid4())[:12]}.pdf"
        s3_client.put_object(
            Bucket=S3_AP_ALIAS,
            Key=file_key, 
            Body=pdf_output, 
            ContentType='application/pdf'
        )


        # 6. 生成 URL (使用 Access Point 隱藏原始 Bucket)
        url = s3_client.generate_presigned_url('get_object', Params={'Bucket': S3_AP_ALIAS, 'Key': file_key}, ExpiresIn=3600)

        # --- ✨ 新增：封面照片 URL (assets 部分) ---
        # 您已經手動在 S3 建立 assets 資料夾並放了 cover.jpg
        image_url = s3_client.generate_presigned_url(
            'get_object',
             Params={
                'Bucket': S3_AP_ALIAS,
                 'Key': 'assets/cover.jpg'
            },
            ExpiresIn=3600
        )

        # 7. 發送 LINE 卡片 (取代原本的實體檔案發送)
        session_attrs = event.get('sessionAttributes', {})
        line_user_id = session_attrs.get('line_user_id')

        print(f"DEBUG - 抓到的 LINE ID: {line_user_id}") 

        if line_user_id and line_user_id != "default-user":
            # ✨ 這裡改呼叫 send_line_button，不要再叫 send_line_file 了
            line_status = send_line_button(
                user_id=line_user_id,
                file_url=url,
                title=data.get('title', '您的專屬行程'),
                image_url=image_url # ✨ 使用 S3 生成的圖片連結
            )
            
            if line_status == 200:
                return format_action_response(event, "✅ 行程卡片已發送至您的 LINE！")
            else:
                # 如果卡片發送失敗，至少回傳一個純文字連結當墊底
                return format_action_response(event, f"✅ PDF 已生成，但卡片發送失敗。請點此下載：{url}")

        # 7. 如果沒有 LINE ID (例如在 AWS Console 測試時)，回傳 Markdown 連結
        display_text = f"✅ PDF 已成功生成！\n[📄 點擊此處下載您的行程檔案]({url})"
        return format_action_response(event, display_text)

    except Exception as e:
        print(f"Error Detail: {str(e)}")
        return format_action_response(event, f"❌ PDF 生成失敗：{str(e)}")

def send_line_button(user_id, file_url, title, image_url):
    # 從環境變數讀取 Token
    LINE_ACCESS_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN", "")
    api_url = "https://api.line.me/v2/bot/message/push"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }
    
    # 這是「按鈕範本」，所有 LINE 帳號都支援
    payload = {
        "to": user_id,
        "messages": [
            {
                "type": "template",
                "altText": "您的行程 PDF 已準備好！請在一小時內下載完成~",
                "template": {
                    "type": "buttons",
                    "thumbnailImageUrl": image_url,    # ✨ 新增圖片網址(使用傳進來的變數)
                    "imageAspectRatio": "square",      # ✨ 設定為 1:1 正方形 (或改用 rectangle)
                    "imageSize": "cover",              # ✨ 圖片填滿容器
                    "imageBackgroundColor": "#FFFFFF",
                    "title": "行程規劃完成!",
                    "text": f"主題：{title[:50]}",      # 限制長度避免報錯
                    "actions": [
                        {
                            "type": "uri",
                            "label": "📄 點我下載 PDF",
                            "uri": file_url
                        }
                    ]
                }
            }
        ]
    }

    try:
        response = requests.post(api_url, headers=headers, json=payload)
        print(f"LINE API Status: {response.status_code}, Response: {response.text}")
        return response.status_code
    except Exception as e:
        print(f"LINE API Request Error: {str(e)}")
        return 500

def format_action_response(event, message, status_code=200):
    """
    修正後的版本：專為 Bedrock Agent Function Call 設計
    """
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get('actionGroup'),
            "function": event.get('function'),
            "functionResponse": {
                "responseBody": {
                    "TEXT": {
                        "body": str(message)
                    }
                }
            }
        }
    } 
    