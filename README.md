# LINE Bot × AWS Bedrock 智慧助理（Serverless）



## Table of Contents

- [專案簡介](#專案簡介)
- [需求定義](#需求定義)
- [架構圖](#架構圖)
- [技術實現](#技術實現)
- [成果展示](#成果展示)
  - [RichMenu](#RichMenu)
  - [api串接](#api串接)
  - [生成pdf功能](#生成pdf功能)


## 專案簡介
本專案打造「日本旅遊小助手」：  
以 **LINE 官方帳號聊天室**作為前端入口，導入 **AWS Bedrock 架構的智慧對話代理人（AI Agent）**，把旅遊規劃變成像「問朋友」一樣的對話體驗。

核心理念：**Zero-Friction（零摩擦）**  
- 使用者 **無需下載新 App、無需學新介面**，只要會傳訊息就能規劃行程  
- 將權威美食資料與 Google Maps 即時資訊匯流到單一對話框，降低多視窗焦慮

## 需求定義
在日本自由行的旅途中，使用者常需要同時操作地圖、交通、部落格、美食、天氣等多個應用程式，資訊彼此斷裂，造成大量「複製、切換、貼上」的操作摩擦（Context Switching Cost），讓旅人陷入數位焦慮。  
主要痛點包含：
- **App 切換疲勞**：地圖/翻譯/匯率/筆記/天氣等多 App 同時操作，繁瑣且耗效能  
- **資訊過載與決策癱瘓**：大量過時文章與農場內容難以辨識真偽  
- **下載門檻高**：旅遊 App 往往「用完即刪」，不想學新 UI  
- **缺乏上下文**：一般搜尋沒有記憶，使用者需反覆重打條件

## 架構圖
<img src=https://github.com/james12390/linebot-aws-serverless/blob/master/image/all/all.png width=80%>

## 技術實現
以 **LINE Bot** 作為使用者入口，後端採 **AWS Serverless** 架構（API Gateway + Lambda）。
<img src=https://github.com/james12390/linebot-aws-serverless/blob/master/image/linebot/linebot.png width=80%>

串接 **AWS Bedrock Agent** 與 **MCP** 功能。
<img src=https://github.com/james12390/linebot-aws-serverless/blob/master/image/api/api1.png width=80%>

並使用 **DynamoDB** 作為記憶/狀態儲存，
<img src=https://github.com/james12390/linebot-aws-serverless/blob/master/image/db/db1.png width=80%>

同時提供 **S3 產出 PDF** 等能力，並配置雲端維運監控。
<img src=https://github.com/james12390/linebot-aws-serverless/blob/master/image/pdf/pdf3.png width=80%>

## 成果展示


<img src=https://github.com/james12390/linebot-aws-serverless/blob/master/image/lineicon/icon1.jpg width=50%>
<img src=https://github.com/james12390/linebot-aws-serverless/blob/master/image/lineicon/icon2.jpg width=50%>

### api 串接
- **google api**
<img src=https://github.com/james12390/linebot-aws-serverless/blob/master/image/api/qpi3.jpg width=50%>

- **openweather api**
<img src=https://github.com/james12390/linebot-aws-serverless/blob/master/image/api/qpi2.jpg width=50%>

- **tripadvisor api**
<img src=https://github.com/james12390/linebot-aws-serverless/blob/master/image/api/qpi1.jpg width=50%>

# 生成 PDF 功能
<img src=https://github.com/james12390/linebot-aws-serverless/blob/master/image/pdf/pdf1.jpg width=50%>
<img src=https://github.com/james12390/linebot-aws-serverless/blob/master/image/pdf/pdf2.jpg width=50%>








