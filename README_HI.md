# SINTU AI STUDIO — शुरुआती संस्करण

## चलाने का तरीका

1. Python 3.10+ इंस्टॉल करें।
2. `pip install -r requirements.txt`
3. `uvicorn app.main:app --host 0.0.0.0 --port 8000`
4. ब्राउज़र में `http://127.0.0.1:8000` खोलें।

## अभी क्या काम करता है

- Responsive Hindi creator dashboard
- FastAPI health/status endpoints
- 61 विशेषज्ञ एजेंटों की registry (सभी Pending)
- Prompt/topic को SQLite में task के रूप में सेव करना
- Recent saved tasks दिखाना

## अभी क्या काम नहीं करता

यह foundation है, पूर्ण AI video generator नहीं। किसी भी AI model provider, image/video generation engine, voice engine, YouTube OAuth/publishing या analytics account को अभी जोड़ा/टेस्ट नहीं किया गया है। इनके लिए official APIs, सुरक्षित credentials और अलग-अलग integration tests आवश्यक हैं।

## सुरक्षा और approval

- API keys chat या source code में न डालें।
- Public publishing और destructive actions से पहले human approval अनिवार्य होगा।
- Paid APIs default रूप से बंद रहेंगी।
- Agent status को verified implementation के बिना Active/Passed न दिखाएँ।
