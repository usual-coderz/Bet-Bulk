# Bet-Bulk

## Setup
cp .env.example .env
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"  # FERNET_KEY me daalo
pip install -r requirements.txt
playwright install chromium
mongod  (ya docker run -p 27017:27017 mongo:7)
python seed.py
python bot.py

## Proxy
Koi file nahi chahiye. Bot start hote hi 5 public source se proxy fetch karke
validate karta hai, valid wale proxy_cache.txt me cache hote hain aur har 20 min
me refresh hote hain. /proxy se live count dekho.

## Note
Redis nahi hai — jobs in-process queue me hain. Bot restart pe pending jobs
Mongo se wapas queue ho jaate hain, lekin chal rahe accounts beech me rukte hain.