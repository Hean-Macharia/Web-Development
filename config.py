import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'
    MONGO_URI = os.environ.get('MONGO_URI') or 'mongodb://localhost:27017/webdev_academy'
    
    # M-Pesa Daraja API credentials
    MPESA_CONSUMER_KEY = os.environ.get('MPESA_CONSUMER_KEY')
    MPESA_CONSUMER_SECRET = os.environ.get('MPESA_CONSUMER_SECRET')
    MPESA_PASSKEY = os.environ.get('MPESA_PASSKEY')
    MPESA_SHORTCODE = os.environ.get('MPESA_SHORTCODE')
    MPESA_CALLBACK_URL = os.environ.get('MPESA_CALLBACK_URL') or 'https://yourdomain.com/callback'