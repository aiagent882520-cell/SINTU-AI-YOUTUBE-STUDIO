# SINTU AI STUDIO — शुरुआती AI Brain संस्करण

## चलाने का तरीका

1. Python 3.10+ इंस्टॉल करें।
2. `pip install -r requirements.txt`
3. `.env.example` की कॉपी बनाकर उसका नाम `.env` रखें।
4. अपनी API key केवल स्थानीय/server `.env` फाइल में डालें।
5. `uvicorn app.main:app --host 0.0.0.0 --port 8000`
6. ब्राउज़र में `http://127.0.0.1:8000` खोलें।

## AI provider configuration

- `AI_PROVIDER=auto`: उपलब्ध provider में OpenAI को प्राथमिकता, अन्यथा Gemini।
- `AI_PROVIDER=openai`: OpenAI Responses API।
- `AI_PROVIDER=gemini`: Google Gemini generateContent API।
- OpenAI model: `OPENAI_MODEL` (default `gpt-5.5`)।
- Gemini model: `GEMINI_MODEL` (default `gemini-2.5-flash`)।

API key बनाना और API billing, ChatGPT या Google AI Studio की सामान्य app subscription से अलग हो सकता है। Provider usage पर शुल्क लग सकता है। बिना key के generation endpoint साफ तौर पर Blocked/503 लौटाता है; नकली output नहीं बनाता।

## अभी क्या काम करता है

- Responsive Hindi creator dashboard
- FastAPI health/status endpoints
- 61 विशेषज्ञ एजेंटों की registry (सभी Pending)
- Prompt/topic को SQLite में task के रूप में सेव करना
- OpenAI और Gemini के लिए server-side text generation adapters
- Provider status में केवल configured true/false; कोई secret वापस नहीं भेजा जाता
- Generated text और task status को SQLite में सेव करना

## अभी क्या काम नहीं करता

यह अभी text-generation slice है, पूर्ण AI video generator नहीं। Image/video generation, voice, rendering, YouTube OAuth/publishing, analytics, autonomous 61-agent orchestration और mobile store apps अभी implement/verify नहीं हुए हैं।

## सुरक्षा

- असली API keys कभी GitHub या browser में न डालें।
- `.env` Git से ignore है; `.env.example` में केवल खाली placeholders हैं।
- Public publishing, destructive actions और financial actions के लिए human approval आवश्यक होगा।
- Paid APIs default रूप से बंद रहेंगी।
- Agent status को verified implementation के बिना Active/Passed न दिखाएँ।
