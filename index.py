from fastapi import FastAPI, Request
from telethon import TelegramClient, StringSession
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import os
import re

app = FastAPI()

# Load and validate environment variables upfront
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
MONGO_URI = os.getenv('MONGO_URI')

if not API_ID or not API_HASH or not MONGO_URI:
    print("ERROR: Missing required environment variables (API_ID, API_HASH, MONGO_URI). Set them in Vercel dashboard.")
    # This will cause the function to fail fast, but we'll handle it in routes

try:
    db_client = AsyncIOMotorClient(MONGO_URI)
    db = db_client['lunar_db']
    print("MongoDB connected successfully.")
except Exception as e:
    print(f"ERROR: MongoDB connection failed: {str(e)}")
    db = None  # Prevent crashes

@app.post('/send_code')
async def send_code(request: Request):
    try:
        print("send_code endpoint called.")  # Logging
        if not API_ID or not API_HASH or not MONGO_URI:
            return {'status': 'error', 'message': 'Server configuration error. Contact admin.'}
        if db is None:
            return {'status': 'error', 'message': 'Database connection failed.'}

        data = await request.json()
        phone = data.get('phone')
        user_id = str(data.get('user_id'))
        print(f"Processing send_code for user {user_id}, phone {phone}")  # Logging

        if not phone or not re.match(r'^\+\d{7,15}$', phone):
            print("Invalid phone format.")  # Logging
            return {'status': 'error', 'message': 'Invalid phone number. Use +countrycode.'}

        client = TelegramClient(StringSession(), int(API_ID), API_HASH)
        await client.connect()
        print("Telegram client connected.")  # Logging

        sent = await client.send_code_request(phone)
        await db.temp_sessions.update_one(
            {'user_id': user_id},
            {'$set': {'phone': phone, 'hash': sent.phone_code_hash, 'createdAt': datetime.utcnow()}},
            upsert=True
        )
        print(f"Code sent successfully for user {user_id}")  # Logging
        return {'status': 'success'}
    except Exception as e:
        print(f"ERROR in send_code: {str(e)}")  # Logging
        return {'status': 'error', 'message': f'Failed to send code: {str(e)}'}
    finally:
        try:
            await client.disconnect()
        except:
            pass

@app.post('/verify')
async def verify(request: Request):
    try:
        print("verify endpoint called.")  # Logging
        if not API_ID or not API_HASH or not MONGO_URI:
            return {'status': 'error', 'message': 'Server configuration error. Contact admin.'}
        if db is None:
            return {'status': 'error', 'message': 'Database connection failed.'}

        data = await request.json()
        user_id = str(data.get('user_id'))
        code = data.get('code')
        password = data.get('password')
        print(f"Processing verify for user {user_id}, code provided: {bool(code)}")  # Logging

        if not code:
            return {'status': 'error', 'message': 'Code is required.'}

        s_data = await db.temp_sessions.find_one({'user_id': user_id})
        if not s_data:
            print("Temp session expired.")  # Logging
            return {'status': 'error', 'message': 'Code expired. Request a new one.'}

        client = TelegramClient(StringSession(), int(API_ID), API_HASH)
        await client.connect()
        print("Telegram client connected for verify.")  # Logging

        await client.sign_in(s_data['phone'], code, phone_code_hash=s_data['hash'])
        if await client.is_user_authorized():
            session_str = client.session.save()
            await db.users.update_one(
                {'user_id': user_id},
                {'$set': {'session': session_str, 'status': 'active', 'paired_at': datetime.utcnow()}},
                upsert=True
            )
            await db.temp_sessions.delete_one({'user_id': user_id})
            print(f"User {user_id} verified successfully.")  # Logging
            return {'status': 'success'}
        else:
            return {'status': '2fa_required'}
    except Exception as e:
        error_str = str(e).lower()
        if 'password' in error_str or '2fa' in error_str:
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
                        print(f"User {user_id} verified with 2FA.")  # Logging
                        return {'status': 'success'}
                    else:
                        return {'status': 'error', 'message': 'Invalid 2FA password.'}
                except Exception as inner_e:
                    print(f"2FA error: {str(inner_e)}")  # Logging
                    return {'status': 'error', 'message': str(inner_e)}
            else:
                return {'status': '2fa_required'}
        print(f"ERROR in verify: {str(e)}")  # Logging
        return {'status': 'error', 'message': f'Verification failed: {str(e)}'}
    finally:
        try:
            await client.disconnect()
        except:
            pass