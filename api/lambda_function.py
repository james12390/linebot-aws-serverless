import os
import json
import urllib.request
import urllib.parse
import logging
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.core import patch_all

# 啟動 X-Ray
patch_all()

logger = logging.getLogger()
logger.setLevel(logging.INFO)
TRIPADVISOR_API_KEY = os.environ.get("TRIPADVISOR_API_KEY", "")
# --- 共用工具 ---
def get_api_key():
    key = os.environ.get('GOOGLE_API_KEY')
    if not key: logger.error("缺少 GOOGLE_API_KEY")
    return key

def call_api_get(url, params):
    try:
        api_key = get_api_key()
        if not api_key: return {"error": "API Key 未設定"}
        params['key'] = api_key
        query_string = urllib.parse.urlencode(params)
        full_url = f"{url}?{query_string}"
        
        with urllib.request.urlopen(full_url) as response:
            if response.status != 200: return {"error": f"HTTP {response.status}"}
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        return {"error": str(e)}

# --- 1. 交通導航 ---
def get_directions(origin, destination, mode="driving"):
    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {"origin": origin, "destination": destination, "mode": mode, "language": "zh-TW"}
    data = call_api_get(url, params)
    
    if "error" in data: return f"系統錯誤: {data['error']}"
    if data.get("status") != "OK": return f"導航失敗: {data.get('status')}"
    if not data.get('routes'): return "找不到路線"
    
    route = data['routes'][0]['legs'][0]
    summary = data['routes'][0]['summary']
    
    # 標準 Google Maps 導航連結
    safe_origin = urllib.parse.quote(origin)
    safe_dest = urllib.parse.quote(destination)
    map_link = f"https://www.google.com/maps/dir/?api=1&origin={safe_origin}&destination={safe_dest}&travelmode={mode}"
    
    return (f"🚗 導航建議 ({mode})：\n"
            f"• 距離: {route['distance']['text']}\n"
            f"• 時間: {route['duration']['text']}\n"
            f"• 路線: {summary}\n"
            f"• 連結: {map_link}")

# --- 2. 查詢詳情 (內部工具) ---
def get_place_details(place_id):
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {"place_id": place_id, "fields": "name,formatted_phone_number,formatted_address,opening_hours,rating,url", "language": "zh-TW"}
    data = call_api_get(url, params)
    
    if "error" in data: return f"目前無法取得資訊，請稍後再試。"
    if data.get("status") != "OK": return f"(無法取得詳情)"
    
    result = data.get("result", {})
    name = result.get("name", "未知地點")
    phone = result.get("formatted_phone_number", "無電話")
    address = result.get("formatted_address", "無地址")
    rating = result.get("rating", "無")
    
    # 修正版：最穩定的 Google Maps 官方連結
    safe_name = urllib.parse.quote(name)
    google_map_url = result.get("url")
    if not google_map_url:
        google_map_url = f"https://www.google.com/maps/search/?api=1&query={safe_name}&query_place_id={place_id}"

    # 簡化營業時間
    opening_info = "無營業資訊"
    if "opening_hours" in result:
        open_now = result["opening_hours"].get("open_now")
        status_text = "🟢 營業中" if open_now else "🔴 已打烊"
        opening_info = status_text 

    # ⚠️ 這裡回傳 Place ID 讓 Agent 看得見
    return (f"名稱: {name} ({rating}星)\n"
            f"ID: {place_id}\n"
            f"電話: {phone}\n"
            f"地址: {address}\n"
            f"狀態: {opening_info}\n"
            f"連結: {google_map_url}")

# --- 3. 搜尋地點 (整合版) ---
def search_places(keyword, location=""):
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    final_query = f"{location} {keyword}".strip()
    params = {"query": final_query, "language": "zh-TW"}
    
    data = call_api_get(url, params)
    
    if "error" in data: return f"目前無法取得資訊，請稍後再試。"
    if data.get("status") not in ["OK", "ZERO_RESULTS"]:
         return f"目前無法取得資訊，請稍後再試。"

    results = data.get("results", [])
    if not results: 
        return f"找不到 '{final_query}'"
    
    # 處理第一筆 (詳細)
    top_result = results[0]
    final_output = []
    
    # ⚠️ 關鍵修正：確保這裡有呼叫 get_place_details
    if top_result.get('place_id'):
        final_output.append(f"【最佳結果】\n{get_place_details(top_result.get('place_id'))}")
    else:
        final_output.append(f"【最佳結果】\n{top_result.get('name')}\n(無詳情)")

    # 處理第 2-3 筆 (簡略)
    if len(results) > 1:
        final_output.append("\n【其他結果】")
        for r in results[1:3]:
            name = r.get('name')
            pid = r.get('place_id', '無ID')
            rating = r.get('rating', '無')
            addr = r.get('formatted_address')
            
            # 修正版：最穩定的 Google Maps 官方連結
            safe_name = urllib.parse.quote(name)
            map_url = f"https://www.google.com/maps/search/?api=1&query={safe_name}"
            
            # ⚠️ 這裡也加上 ID，預防 Agent 想查別家
            final_output.append(f"- {name} ({rating}星)\n  ID: {pid}\n  地址: {addr}\n  (連結: {map_url})")

    return "\n".join(final_output)

# --- 4. 天氣查詢  ---
def get_weather(location):
    # 讀取環境變數中的兩把鑰匙
    google_key = os.environ.get('GOOGLE_API_KEY')
    ow_key = os.environ.get('OPENWEATHER_API_KEY')
    
    if not google_key or not ow_key:
        return "目前無法取得資訊，請稍後再試。"

    try:
        # 步驟 1：使用 Google Geocoding 將「地標」轉換為「經緯度」
        # Google 的定位能力極強，能輕鬆辨識「東京車站」
        geo_url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(location)}&key={google_key}&language=zh-TW"
        
        with urllib.request.urlopen(geo_url, timeout=5) as resp:
            geo_data = json.loads(resp.read().decode('utf-8'))
        
        if geo_data.get("status") != "OK":
            return f"找不到地點：{location}，請嘗試輸入更準確的地標名稱。"
        
        # 提取精確座標
        loc = geo_data["results"][0]["geometry"]["location"]
        lat, lon = loc["lat"], loc["lng"]
        formatted_name = geo_data["results"][0]["formatted_address"]

        # 步驟 2：使用座標呼叫 OpenWeather API
        # 使用 lat, lon 參數代替 q 參數，這在日本地區 100% 穩定
        weather_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={ow_key}&units=metric&lang=zh_tw"
        
        with urllib.request.urlopen(weather_url, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            
        main = data.get("main", {})
        weather = data.get("weather", [{}])[0]
        
        # 回傳親切的導遊格式
        return (f"🌡️ {formatted_name} 目前天氣：\n"
                f"• 狀態: {weather.get('description', '未知')}\n"
                f"• 氣溫: {main.get('temp')}°C (體感 {main.get('feels_like')}°C)\n"
                f"• 濕度: {main.get('humidity')}%\n"
                f"• 提醒: 座標定位由 Google 提供，氣象數據由 OpenWeather 提供。祝您旅途愉快！")

    except Exception as e:
        logger.error(f"Weather Tool Error: {str(e)}")
        return f"暫時無法取得 {location} 的天氣資訊，請稍後再試。"


def get_location_id(query):
    """第一步：將地名換成 Location ID"""
    encoded_query = urllib.parse.quote(query)
    url = f"https://api.content.tripadvisor.com/api/v1/location/search?key={TRIPADVISOR_API_KEY}&searchQuery={encoded_query}&category=hotels&address={encoded_query}&language=zh_TW"

    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read().decode())
        if data.get('data'):
            return data.get('data', [])
    return None, None

def get_hotels_by_id(location_id):
    """第二步：拿 Location ID 換取飯店清單與評分"""
    # 注意這裡的路徑：location/{id}/search
    print(location_id)
    url = f"https://api.content.tripadvisor.com/api/v1/location/{location_id}/details?key={TRIPADVISOR_API_KEY}&language=zh_TW&currency=TWD"
    print(url)
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode())

def get_hotels(data1):
    result_text =""
    for i in data1[::3]:
        print(i)
        print(i.get('name'))
        actual_name = i.get('name')
        loc_id = i.get('location_id')
        if loc_id:
            # 2. 取得飯店
            hotels_data = get_hotels_by_id(loc_id)
                
            # 3. 解析評分與資料
            hotel_lines = []

            name = hotels_data.get('name', '未知飯店')
            rating = hotels_data.get('rating', '暫無') # 抓取評分欄位
            price_level = hotels_data.get('price_level', '暫無') # 抓取價格欄位
            web_url = hotels_data.get('web_url','暫無') 
            hotel_lines.append(f"- {name} (評分: {rating}\n⭐ 價格 {price_level}\n網址{web_url}\n")
                                  
            if hotel_lines:
                result_text += f"為您找到{actual_name}附近的推薦飯店：\n" + "\n".join(hotel_lines)+"\n"
            else:
                result_text = f"找到地點{actual_name}，但查無飯店資料。"

    return result_text    

def lambda_handler(event, context):
    # 紀錄完整的 Event 內容，方便在 CloudWatch 查看 Bedrock 傳了什麼
    logger.info("Received Event: " + json.dumps(event, ensure_ascii=False))
    
    # 解析 Bedrock 傳來的參數
    actionGroup = event.get('actionGroup', 'defaultGroup')
    function_name = event.get('function', '')
    parameters = event.get('parameters', [])
    
    # 將參數轉成字典格式，方便讀取
    p = {param['name']: param['value'] for param in parameters}
    
    # 預設回應內容
    response_body = "功能執行異常"
    
    try:
        # 根據 Bedrock 請求的 function 名稱進行路由
        if function_name == 'get_directions':
            # 假設你已有 get_directions 函數
            response_body = get_directions(p.get('origin'), p.get('destination'), p.get('mode', 'driving'))
            
        elif function_name == 'search_places':
            # 假設你已有 search_places 函數
            response_body = search_places(p.get('keyword'), p.get('location', ''))
            
        elif function_name == 'get_place_details':
            # 假設你已有 get_place_details 函數
            response_body = get_place_details(p.get('place_id'))
            
        elif function_name == 'get_weather':
            # 執行剛剛寫好的 Google Weather API 查詢
            response_body = get_weather(p.get('location'))
        elif function_name == "search_hotels_by_name":
            location_name = p.get("locationName")
            data1 = get_location_id(location_name)
            response_body = get_hotels(data1)
        else:
            response_body = f"不支援的功能：{function_name}"
            
    except Exception as e:
        logger.error(f"Lambda Handler Crash: {str(e)}")
        response_body = f"執行例外: {str(e)}"

    # ⚠️ 重要：回傳格式必須嚴格遵守 Bedrock Action Group 規範
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": actionGroup,
            "function": function_name,
            "functionResponse": {
                "responseBody": {
                    "TEXT": { "body": str(response_body) }
                }
            }
        }
    }