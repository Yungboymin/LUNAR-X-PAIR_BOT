from fastapi import FastAPI, Request
from telethon import TelegramClient, StringSession
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import os
import re

app = FastAPI()

# Load from environment variables (set in Vercel dashboard)
API_ID = int(os.getenv('API_ID', '36531006'))
API_HASH = os.getenv('API_HASH', '8b4df3bdc80ff44b80a1d788d4e55eb2')
MONGO_URI = os.getenv('MONGO_URI', 'mongodb+srv://eternlxz516_db_user:1asJy8YrLKj4cL73@lunar.6ltkilo.mongodb.net/?appName=Lunar')

db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client['lunar_db']

@app.post('/send_code')  # Updated: No /api/
async def send_code(request: Request):
    data = await request.json()
    phone = data.get('phone')
    user_id = str(data.get('user_id'))

    if not phone or not re.match(r'^\+\d{7,15}$', phone):
        return {'status': 'error', 'message': 'Invalid phone number. Use +countrycode.'}

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()

    try:
        sent = await client.send_code_request(phone)
        await db.temp_sessions.update_one(
            {'user_id': user_id},
            {'$set': {'phone': phone, 'hash': sent.phone_code_hash, 'createdAt': datetime.utcnow()}},
            upsert=True
        )
        print(f'Code sent for user {user_id}')  # Logging
        return {'status': 'success'}
    except Exception as e:
        print(f'Error sending code: {e}')  # Logging
        return {'status': 'error', 'message': str(e)}
    finally:
        await client.disconnect()

@app.post('/verify')  # Updated: No /api/
async def verify(request: Request):
    data = await request.json()
    user_id = str(data.get('user_id'))
    code = data.get('code')
    password = data.get('password')

    if not code:
        return {'status': 'error', 'message': 'Code is required.'}

    s_data = await db.temp_sessions.find_one({'user_id': user_id})
    if not s_data:
        return {'status': 'error', 'message': 'Code expired. Request a new one.'}

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()

    try:
        await client.sign_in(s_data['phone'], code, phone_code_hash=s_data['hash'])
        if await client.is_user_authorized():
            session_str = client.session.save()
            await db.users.update_one(
                {'user_id': user_id},
                {'$set': {'session': session_str, 'status': 'active', 'paired_at': datetime.utcnow()}},
                upsert=True
            )
            await db.temp_sessions.delete_one({'user_id': user_id})
            print(f'User {user_id} verified successfully')  # Logging
            return {'status': 'success'}
        else:
            return {'status': '2fa_required'}
    except Exception as e:
        if 'password' in str(e).lower() or '2fa' in str(e).lower():
            if password:
                try:
                    await client.sign_in(password=password)
                    if await client.is_user_authorized():
                        session_str = client.session.save()
                        await db.users.update_one(
                            {'user_id': user_id},
                            {'$set': {'session': session_str, 'status': 'active', 'paired_at': datetime.utcnow()}},
                            upsert=True
                        )
                        await db.temp_sessions.delete_one({'user_id': user_id})
                        return {'status': 'success'}
                    else:
                        return {'status': 'error', 'message': 'Invalid 2FA password.'}
                except Exception as inner_e:
                    return {'status': 'error', 'message': str(inner_e)}
            else:
                return {'status': '2fa_required'}
        print(f'Verification error for user {user_id}: {e}')  # Logging
        return {'status': 'error', 'message': str(e)}
    finally:
        await client.disconnect()