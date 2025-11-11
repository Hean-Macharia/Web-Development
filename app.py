from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_pymongo import PyMongo
from bson.objectid import ObjectId
from datetime import datetime, timedelta
from functools import wraps
import requests
import base64
import json
import time
import threading
import os
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import secrets
import string
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Load all sensitive configuration from environment variables
app.secret_key = os.getenv('SECRET_KEY', 'fallback-secret-key-change-in-production')

# MongoDB configuration from environment variables
MONGO_URI = os.getenv('MONGODB_URI')
if not MONGO_URI:
    print("❌ MONGODB_URI environment variable is required!")
    # Fallback for development
    MONGO_URI = "mongodb+srv://iconichean:1Loye8PM3YwlV5h4@cluster0.meufk73.mongodb.net/webdev_courses?retryWrites=true&w=majority"

app.config["MONGO_URI"] = MONGO_URI

try:
    mongo = PyMongo(app)
    # Test the connection
    mongo.db.command('ping')
    print("✅ MongoDB connected successfully!")
except Exception as e:
    print(f"❌ MongoDB connection failed: {e}")
    # Create a mock mongo object for development
    class MockMongo:
        class MockDB:
            def __getattr__(self, name):
                return self
            def find_one(self, *args, **kwargs):
                return None
            def insert_one(self, *args, **kwargs):
                class Result:
                    inserted_id = "mock_id"
                return Result()
            def update_one(self, *args, **kwargs):
                return None
            def find(self, *args, **kwargs):
                return []
        db = MockDB()
    mongo = MockMongo()

# M-Pesa Daraja API credentials from environment variables
MPESA_CONSUMER_KEY = os.getenv('MPESA_CONSUMER_KEY')
MPESA_CONSUMER_SECRET = os.getenv('MPESA_CONSUMER_SECRET')
MPESA_PASSKEY = os.getenv('MPESA_PASSKEY')
MPESA_SHORTCODE = os.getenv('MPESA_SHORTCODE')
MPESA_CALLBACK_URL = os.getenv('MPESA_CALLBACK_URL', 'https://web-development-6fdl.onrender.com/callback')

# Email configuration from environment variables
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_EMAIL = os.getenv('SMTP_EMAIL')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')

# Validate required environment variables
required_env_vars = {
    'MPESA_CONSUMER_KEY': MPESA_CONSUMER_KEY,
    'MPESA_CONSUMER_SECRET': MPESA_CONSUMER_SECRET,
    'MPESA_PASSKEY': MPESA_PASSKEY,
    'MPESA_SHORTCODE': MPESA_SHORTCODE,
}

missing_vars = [var for var, value in required_env_vars.items() if not value]
if missing_vars:
    print(f"⚠️  Missing MPesa environment variables: {', '.join(missing_vars)}")
    print("🔧 MPesa features will not work properly")

if not SMTP_EMAIL or not SMTP_PASSWORD:
    print("⚠️  Missing email configuration - password reset emails will not be sent")

# Payment settings - Different prices for different courses
COURSE_PRICES = {
    'webdev': 1,      # 1 KSH for testing
    'graphic': 1,     # 1 KSH for testing  
    'cybersecurity': 2  # 2 KSH for testing (different price)
}

SIMULATION_MODE = False  # DISABLED - Using real MPesa

# External course links
COURSE_LINKS = {
    'webdev': {
        'html': 'https://www.w3schools.com/html/',
        'css': 'https://www.w3schools.com/css/',
        'python': 'https://www.w3schools.com/python/'
    },
    'graphic': {
        'main': 'https://alison.com/topic/learn/83010/learning-outcomes'
    },
    'cybersecurity': {
        'main': 'https://www.w3schools.com/cybersecurity/index.php'
    }
}

# Course descriptions for the homepage
COURSE_DESCRIPTIONS = {
    'webdev': {
        'title': 'Web Development',
        'description': 'Learn HTML, CSS, JavaScript, and Python to build modern, responsive websites and web applications. This comprehensive course covers front-end and back-end development.',
        'features': [
            'HTML5 & CSS3 Fundamentals',
            'Responsive Web Design',
            'JavaScript Programming',
            'Python Backend Development',
            'Database Integration'
        ]
    },
    'graphic': {
        'title': 'Graphic Design',
        'description': 'Master the principles of graphic design, learn to use industry-standard tools, and create stunning visual content for digital and print media.',
        'features': [
            'Design Principles & Theory',
            'Adobe Creative Suite',
            'Logo & Brand Identity Design',
            'Typography & Layout',
            'Digital Illustration'
        ]
    },
    'cybersecurity': {
        'title': 'Cyber Security',
        'description': 'Learn essential cybersecurity skills to protect systems and networks from digital attacks. Master security fundamentals, threat detection, and risk management.',
        'features': [
            'Cybersecurity Fundamentals',
            'Network Security',
            'Threat Detection & Prevention',
            'Risk Management',
            'Ethical Hacking Basics'
        ]
    }
}

# Global dictionary to track payment status
payment_status = {}
payment_timestamps = {}  # Track when payments were initiated

# Mock user data for development (remove in production)
mock_users = []
mock_payments = []

def get_mpesa_access_token():
    """Get M-Pesa API access token"""
    if not MPESA_CONSUMER_KEY or not MPESA_CONSUMER_SECRET:
        print("❌ MPesa credentials not configured")
        return None
        
    try:
        url = 'https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials'
        auth = (MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET)
        response = requests.get(url, auth=auth, timeout=10)
        if response.status_code == 200:
            token = response.json()['access_token']
            print("✅ MPesa access token obtained successfully")
            return token
        else:
            print(f"❌ MPesa token error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ MPesa token exception: {e}")
        return None

def initiate_stk_push(phone_number, amount, account_reference):
    """Initiate STK push for payment"""
    if SIMULATION_MODE:
        print(f"🎯 SIMULATION MODE: Simulating STK push to {phone_number} for KSh {amount}")
        return {
            "MerchantRequestID": f"SIM_{int(time.time())}",
            "CheckoutRequestID": f"SIM_{account_reference}",
            "ResponseCode": "0",
            "ResponseDescription": "Success",
            "CustomerMessage": "Success. Request accepted for processing"
        }
    
    access_token = get_mpesa_access_token()
    if not access_token:
        print("❌ Failed to get MPesa access token")
        return None
    
    url = 'https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest'
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password = base64.b64encode(f"{MPESA_SHORTCODE}{MPESA_PASSKEY}{timestamp}".encode()).decode()
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        "BusinessShortCode": MPESA_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone_number,
        "PartyB": MPESA_SHORTCODE,
        "PhoneNumber": phone_number,
        "CallBackURL": MPESA_CALLBACK_URL,
        "AccountReference": account_reference,
        "TransactionDesc": "Course Payment"
    }
    
    try:
        print(f"🔄 Sending REAL MPesa STK push to {phone_number} for KSh {amount}")
        print(f"📞 Callback URL being used: {MPESA_CALLBACK_URL}")
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        print(f"📡 MPesa API Response: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ STK Push initiated successfully: {result.get('ResponseDescription')}")
            print(f"📋 CheckoutRequestID: {result.get('CheckoutRequestID')}")
            print(f"📋 MerchantRequestID: {result.get('MerchantRequestID')}")
            return result
        else:
            print(f"❌ STK Push failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ STK Push exception: {e}")
        return None

def process_payment_callback_fast(callback_data):
    """Process MPesa callback quickly in a separate thread - ONLY FOR REAL MPESA CALLBACKS"""
    def process():
        start_time = time.time()
        try:
            print(f"⚡ FAST PROCESSING: Starting REAL MPesa callback processing at {datetime.now()}")
            
            if callback_data and 'Body' in callback_data:
                stk_callback = callback_data['Body']['stkCallback']
                checkout_request_id = stk_callback['CheckoutRequestID']
                result_code = stk_callback['ResultCode']
                result_desc = stk_callback.get('ResultDesc', 'No description')
                
                print(f"🔍 REAL MPesa CALLBACK - CheckoutID: {checkout_request_id}, ResultCode: {result_code}")
                
                # Find payment record quickly
                payment_record = None
                try:
                    payment_record = mongo.db.payments.find_one({'checkout_request_id': checkout_request_id})
                    if not payment_record:
                        for p in mock_payments:
                            if p.get('checkout_request_id') == checkout_request_id:
                                payment_record = p
                                break
                except Exception as e:
                    print(f"❌ REAL MPesa CALLBACK - Error finding payment record: {e}")
                
                if payment_record:
                    transaction_ref = payment_record['transaction_ref']
                    print(f"🎯 REAL MPesa CALLBACK - Found payment: {transaction_ref}")
                    
                    if result_code == 0:
                        # Payment successful - extract MPesa receipt (first 10 characters)
                        mpesa_receipt = None
                        
                        # Method 1: Extract from CallbackMetadata
                        if 'CallbackMetadata' in stk_callback:
                            for item in stk_callback['CallbackMetadata']['Item']:
                                if item['Name'] == 'MpesaReceiptNumber':
                                    mpesa_receipt = item['Value']
                                    # Take first 10 characters for payment confirmation
                                    if mpesa_receipt and len(mpesa_receipt) >= 10:
                                        mpesa_receipt = mpesa_receipt[:10]
                                        print(f"💰 REAL MPesa CALLBACK - Receipt from metadata: {mpesa_receipt}")
                                    else:
                                        print(f"⚠️ REAL MPesa CALLBACK - Short receipt: {mpesa_receipt}")
                                    break
                        
                        # Method 2: Extract from ResultDesc if not found in metadata
                        if not mpesa_receipt and 'ResultDesc' in stk_callback:
                            desc = stk_callback['ResultDesc']
                            # Look for patterns like "TKA9Z9O903" in the description
                            receipt_match = re.search(r'[A-Z0-9]{10,}', desc)
                            if receipt_match:
                                mpesa_receipt = receipt_match.group()[:10]
                                print(f"💰 REAL MPesa CALLBACK - Receipt from description: {mpesa_receipt}")
                        
                        if not mpesa_receipt:
                            mpesa_receipt = "UNKNOWN_RCPT"
                            print("⚠️ REAL MPesa CALLBACK - No receipt found, using default")
                        
                        # FAST DATABASE UPDATE - Update payment record with receipt
                        update_data = {
                            'status': 'completed',
                            'mpesa_receipt': mpesa_receipt,
                            'completed_at': datetime.now(),
                            'callback_processed_at': datetime.now(),
                            'processing_time_seconds': round(time.time() - start_time, 2),
                            'callback_data': callback_data
                        }
                        
                        try:
                            result = mongo.db.payments.update_one(
                                {'checkout_request_id': checkout_request_id},
                                {'$set': update_data}
                            )
                            if result.modified_count > 0:
                                print(f"✅ REAL MPesa CALLBACK - Payment updated with receipt: {mpesa_receipt}")
                            else:
                                print(f"⚠️ REAL MPesa CALLBACK - No documents modified")
                        except Exception as e:
                            print(f"❌ REAL MPesa CALLBACK - Database update error: {e}")
                            # Update mock payment
                            for p in mock_payments:
                                if p.get('checkout_request_id') == checkout_request_id:
                                    p.update(update_data)
                                    break
                        
                        # CRITICAL FIX: Update payment status in BOTH memory and database
                        payment_status[transaction_ref] = 'success'
                        print(f"🎉 REAL MPesa CALLBACK - PAYMENT SUCCESS: {transaction_ref}, Receipt: {mpesa_receipt}")
                        
                        # IMMEDIATELY update user's paid courses
                        try:
                            user_id = payment_record['user_id']
                            course_type = payment_record['course_type']
                            
                            user_update_result = mongo.db.users.update_one(
                                {'_id': ObjectId(user_id) if not user_id.startswith('mock') else user_id},
                                {'$addToSet': {'paid_courses': course_type}}
                            )
                            
                            if user_update_result.modified_count > 0:
                                print(f"✅ REAL MPesa CALLBACK - User {user_id} granted access to {course_type}")
                            else:
                                print(f"ℹ️ REAL MPesa CALLBACK - User {user_id} already has access to {course_type}")
                                
                        except Exception as e:
                            print(f"❌ REAL MPesa CALLBACK - Error updating user: {e}")
                        
                    else:
                        # Payment failed
                        update_data = {
                            'status': 'failed',
                            'completed_at': datetime.now(),
                            'error_description': result_desc,
                            'callback_processed_at': datetime.now(),
                            'processing_time_seconds': round(time.time() - start_time, 2),
                            'callback_data': callback_data
                        }
                        
                        try:
                            mongo.db.payments.update_one(
                                {'checkout_request_id': checkout_request_id},
                                {'$set': update_data}
                            )
                            print(f"❌ REAL MPesa CALLBACK - Payment failed: {transaction_ref}, Reason: {result_desc}")
                        except Exception as e:
                            print(f"❌ REAL MPesa CALLBACK - Database update error: {e}")
                            for p in mock_payments:
                                if p.get('checkout_request_id') == checkout_request_id:
                                    p.update(update_data)
                                    break
                        
                        payment_status[transaction_ref] = 'failed'
                        print(f"💥 REAL MPesa CALLBACK - PAYMENT FAILED: {transaction_ref}")
                
                else:
                    print(f"⚠️ REAL MPesa CALLBACK - No payment record found for: {checkout_request_id}")
            
            processing_time = round(time.time() - start_time, 2)
            print(f"⏱️ REAL MPesa CALLBACK - Completed in {processing_time} seconds")
            
        except Exception as e:
            processing_time = round(time.time() - start_time, 2)
            print(f"❌ REAL MPesa CALLBACK - Error: {e}")
            print(f"⏱️ REAL MPesa CALLBACK - Failed after {processing_time} seconds")
    
    # Start processing in a separate thread for maximum speed
    thread = threading.Thread(target=process)
    thread.daemon = True
    thread.start()
    return thread

@app.route('/')
def index():
    """Home page with course cards"""
    return render_template('index.html', course_descriptions=COURSE_DESCRIPTIONS, course_prices=COURSE_PRICES)

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration"""
    if request.method == 'POST':
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        email = request.form['email']
        index_number = request.form['index_number']
        phone = request.form['phone']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        # Validate password confirmation
        if password != confirm_password:
            return render_template('register.html', error="Passwords do not match")
        
        # Validate password strength
        if len(password) < 8:
            return render_template('register.html', error="Password must be at least 8 characters long")
        
        if not re.search(r'[a-z]', password):
            return render_template('register.html', error="Password must contain at least one lowercase letter")
        
        if not re.search(r'[A-Z]', password):
            return render_template('register.html', error="Password must contain at least one uppercase letter")
        
        if not re.search(r'\d', password):
            return render_template('register.html', error="Password must contain at least one number")
        
        if not re.search(r'[@$!%*?&]', password):
            return render_template('register.html', error="Password must contain at least one special character (@$!%*?&)")
        
        # Validate phone number format (10 digits starting with 07 or 01)
        if not re.match(r'^(07\d{8}|01\d{8})$', phone):
            return render_template('register.html', error="Invalid phone number format. Use 10-digit number starting with 07 or 01 (e.g., 0712345678)")
        
        # Combine names for username
        username = f"{first_name} {last_name}".strip()
        
        # Check if user already exists
        try:
            existing_user = mongo.db.users.find_one({'$or': [{'email': email}, {'index_number': index_number}]})
            if existing_user:
                return render_template('register.html', error="User with this email or index number already exists")
        except Exception as e:
            print(f"Database error: {e}")
            for user in mock_users:
                if user['email'] == email or user['index_number'] == index_number:
                    return render_template('register.html', error="User with this email or index number already exists")
        
        # Create new user
        hashed_password = generate_password_hash(password)
        user_data = {
            'first_name': first_name,
            'last_name': last_name,
            'username': username,
            'email': email,
            'index_number': index_number,
            'phone': phone,
            'password': hashed_password,
            'paid_courses': [],
            'created_at': datetime.now()
        }
        
        try:
            result = mongo.db.users.insert_one(user_data)
            user_data['_id'] = result.inserted_id
            print(f"✅ User registered: {email}")
        except Exception as e:
            print(f"Insert error, using mock: {e}")
            user_data['_id'] = f"mock_{len(mock_users)}"
            mock_users.append(user_data)
        
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if request.method == 'POST':
        email = request.form['email']
        index_number = request.form['index_number']
        password = request.form['password']
        
        # Find user
        try:
            user = mongo.db.users.find_one({'email': email, 'index_number': index_number})
        except Exception as e:
            print(f"Login database error: {e}")
            user = None
            for u in mock_users:
                if u['email'] == email and u['index_number'] == index_number:
                    user = u
                    break
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = str(user.get('_id', 'mock_id'))
            session['username'] = user['username']
            session['login_time'] = datetime.now().isoformat()
            session['is_admin'] = user.get('email') in ADMIN_EMAILS
            
            print(f"✅ User logged in: {email}")
            if session['is_admin']:
                print(f"👑 Admin user logged in: {email}")
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('courses'))
        else:
            return render_template('login.html', error="Invalid credentials")
    
    return render_template('login.html')

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Forgot password page"""
    if request.method == 'POST':
        email = request.form['email']
        
        # Find user by email
        try:
            user = mongo.db.users.find_one({'email': email})
            if not user:
                # Also check mock users for development
                for u in mock_users:
                    if u['email'] == email:
                        user = u
                        break
        except Exception as e:
            print(f"Database error: {e}")
            user = None
        
        if user:
            # Generate reset token
            reset_token = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
            
            # Store reset token in database with expiration (1 hour)
            reset_expiry = datetime.now() + timedelta(hours=1)
            
            try:
                mongo.db.users.update_one(
                    {'email': email},
                    {'$set': {
                        'reset_token': reset_token, 
                        'reset_token_expiry': reset_expiry
                    }}
                )
                success = True
            except Exception as e:
                print(f"Error storing reset token: {e}")
                success = False
                # For mock users, add to user object
                for u in mock_users:
                    if u['email'] == email:
                        u['reset_token'] = reset_token
                        u['reset_token_expiry'] = reset_expiry
                        success = True
                        break
            
            if success:
                # Send reset email
                email_sent = send_reset_email(email, reset_token)
                if email_sent:
                    return render_template('forgot_password.html', 
                                         success='Password reset instructions have been sent to your email.')
                else:
                    return render_template('forgot_password.html', 
                                         error='Failed to send reset email. Please try again.')
            else:
                return render_template('forgot_password.html', 
                                     error='Failed to process reset request. Please try again.')
        else:
            return render_template('forgot_password.html', 
                                 error='No account found with that email address.')
    
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Reset password page"""
    # Check if token is valid and not expired
    try:
        user = mongo.db.users.find_one({'reset_token': token})
        if not user:
            for u in mock_users:
                if u.get('reset_token') == token:
                    user = u
                    break
    except Exception as e:
        print(f"Database error: {e}")
        user = None
    
    if not user:
        return render_template('reset_password.html', token_invalid=True)
    
    # Check token expiry
    expiry_time = user.get('reset_token_expiry')
    if expiry_time and datetime.now() > expiry_time:
        return render_template('reset_password.html', token_invalid=True)
    
    if request.method == 'POST':
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']
        
        # Validate passwords match
        if new_password != confirm_password:
            return render_template('reset_password.html', token=token, 
                                 error="Passwords do not match")
        
        # Validate password strength
        if len(new_password) < 8:
            return render_template('reset_password.html', token=token,
                                 error="Password must be at least 8 characters long")
        
        if not re.search(r'[a-z]', new_password):
            return render_template('reset_password.html', token=token,
                                 error="Password must contain at least one lowercase letter")
        
        if not re.search(r'[A-Z]', new_password):
            return render_template('reset_password.html', token=token,
                                 error="Password must contain at least one uppercase letter")
        
        if not re.search(r'\d', new_password):
            return render_template('reset_password.html', token=token,
                                 error="Password must contain at least one number")
        
        if not re.search(r'[@$!%*?&]', new_password):
            return render_template('reset_password.html', token=token,
                                 error="Password must contain at least one special character (@$!%*?&)")
        
        # Update password
        hashed_password = generate_password_hash(new_password)
        
        try:
            result = mongo.db.users.update_one(
                {'reset_token': token},
                {'$set': {'password': hashed_password}, 
                 '$unset': {'reset_token': '', 'reset_token_expiry': ''}}
            )
            if result.modified_count > 0:
                print(f"✅ Password reset for user: {user['email']}")
            else:
                print(f"⚠️ No user updated for password reset")
        except Exception as e:
            print(f"Error updating password: {e}")
            # For mock users
            for u in mock_users:
                if u.get('reset_token') == token:
                    u['password'] = hashed_password
                    u.pop('reset_token', None)
                    u.pop('reset_token_expiry', None)
                    break
        
        return redirect(url_for('login', reset_success=True))
    
    return render_template('reset_password.html', token=token, token_invalid=False)

def send_reset_email(email, reset_token):
    """Send password reset email"""
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print(f"🔗 RESET LINK for {email}: https://web-development-6fdl.onrender.com/reset-password/{reset_token}")
        print("⚠️ Email not sent - SMTP credentials not configured")
        return True
        
    try:
        # Create message
        subject = "Password Reset Request - Devzen CreationsTech Academy"
        reset_link = f"https://web-development-6fdl.onrender.com/reset-password/{reset_token}"
        
        message = MIMEMultipart()
        message["From"] = SMTP_EMAIL
        message["To"] = email
        message["Subject"] = subject
        
        # Email body
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px;">
                <h2 style="color: #4e73df; text-align: center;">Password Reset Request</h2>
                <p>Hello,</p>
                <p>You requested to reset your password for Devzen CreationsTech Academy.</p>
                <p>Click the link below to reset your password:</p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_link}" style="background-color: #4e73df; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">
                        Reset Your Password
                    </a>
                </div>
                <p style="color: #666; font-size: 14px;">
                    <strong>Note:</strong> This link will expire in 1 hour for security reasons.
                </p>
                <p>If you didn't request this reset, please ignore this email.</p>
                <br>
                <p>Best regards,<br><strong>Devzen CreationsTech Academy Team</strong></p>
            </div>
        </body>
        </html>
        """
        
        message.attach(MIMEText(body, "html"))
        
        # Send email
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.send_message(message)
        
        print(f"✅ Reset email sent to {email}")
        return True
        
    except Exception as e:
        print(f"❌ Error sending reset email: {e}")
        # Fallback: log the reset link
        print(f"🔗 RESET LINK for {email}: https://web-development-6fdl.onrender.com/reset-password/{reset_token}")
        return False

@app.route('/logout')
def logout():
    """User logout"""
    session.clear()
    return redirect(url_for('index'))

@app.route('/payment/<course_type>', methods=['GET', 'POST'])
def payment(course_type):
    """Payment page - REAL MPESA ONLY"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Get course price
    amount = COURSE_PRICES.get(course_type, 1)  # Default to 1 KSH if course not found
    
    if request.method == 'POST':
        phone = request.form['phone']
        
        # Validate phone number format (10 digits starting with 07 or 01)
        if not re.match(r'^(07|01)\d{8}$', phone):
            return render_template('payment.html', course_type=course_type, 
                                 error="Invalid phone number format. Use 10-digit number starting with 07 or 01 (e.g., 0712345678)",
                                 amount=amount,
                                 course_title=COURSE_DESCRIPTIONS.get(course_type, {}).get('title', 'Course'))

        # Convert 10-digit format to 254 format for MPesa
        if phone.startswith('07'):
            phone = '254' + phone[1:]  # Convert 0712345678 to 254712345678
        elif phone.startswith('01'):
            phone = '254' + phone[1:]  # Convert 0112345678 to 254112345678
        
        print(f"📱 Converted phone number: {phone}")
        
        # Generate unique transaction reference
        transaction_ref = f"COURSE_{course_type.upper()}_{session['user_id']}_{int(time.time())}"
        
        print(f"🔄 Processing REAL MPesa payment for {phone}, amount: KSh {amount}, ref: {transaction_ref}")
        
        # Real MPesa integration
        stk_response = initiate_stk_push(phone, amount, transaction_ref)
        
        if stk_response and stk_response.get('ResponseCode') == '0':
            # Store payment attempt in database
            payment_data = {
                'user_id': session['user_id'],
                'course_type': course_type,
                'phone': phone,
                'amount': amount,
                'transaction_ref': transaction_ref,
                'checkout_request_id': stk_response['CheckoutRequestID'],
                'merchant_request_id': stk_response['MerchantRequestID'],
                'status': 'pending',
                'created_at': datetime.now()
            }
            
            try:
                mongo.db.payments.insert_one(payment_data)
                print(f"✅ Payment record saved: {transaction_ref}")
            except Exception as e:
                print(f"❌ Payment save error: {e}")
                mock_payments.append(payment_data)
            
            # Store in global payment status tracker
            payment_status[transaction_ref] = 'pending'
            payment_timestamps[transaction_ref] = time.time()
            
            print(f"✅ STK Push sent successfully to {phone}. Check your phone to complete payment.")
            print(f"⏳ Waiting for MPesa callback at: {MPESA_CALLBACK_URL}")
            return redirect(url_for('payment_wait', transaction_ref=transaction_ref))
        else:
            error_msg = "Failed to initiate MPesa payment. "
            if stk_response:
                error_msg += f"MPesa Error: {stk_response.get('ResponseDescription', 'Unknown error')}"
            else:
                error_msg += "Please check your phone number and try again. Ensure it's a valid Safaricom number."
            return render_template('payment.html', course_type=course_type, error=error_msg, amount=amount,
                                 course_title=COURSE_DESCRIPTIONS.get(course_type, {}).get('title', 'Course'))
    
    return render_template('payment.html', course_type=course_type, amount=amount,
                         course_title=COURSE_DESCRIPTIONS.get(course_type, {}).get('title', 'Course'))

@app.route('/payment/wait/<transaction_ref>')
def payment_wait(transaction_ref):
    """Payment waiting page"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Extract course_type from transaction_ref for the retry button
    course_type = transaction_ref.split('_')[1].lower()
    
    print(f"🔄 Payment wait page for: {transaction_ref}")
    return render_template('payment_wait.html', 
                         transaction_ref=transaction_ref, 
                         course_type=course_type)

@app.route('/payment/status/<transaction_ref>')
def payment_status_check(transaction_ref):
    """Check payment status (AJAX endpoint) - FIXED VERSION"""
    print(f"🔄 Checking payment status for: {transaction_ref}")
    
    # CRITICAL FIX: Check BOTH memory status AND database status
    status_from_memory = payment_status.get(transaction_ref, 'pending')
    
    # Also check database directly as backup
    try:
        payment_record = mongo.db.payments.find_one({'transaction_ref': transaction_ref})
        if payment_record:
            status_from_db = payment_record.get('status', 'pending')
            
            # If database says completed but memory doesn't, sync them
            if status_from_db == 'completed' and status_from_memory != 'success':
                print(f"🔄 SYNCING: Database shows completed, updating memory status for {transaction_ref}")
                payment_status[transaction_ref] = 'success'
                status_from_memory = 'success'
            
            # If database says failed but memory doesn't, sync them
            elif status_from_db == 'failed' and status_from_memory != 'failed':
                print(f"🔄 SYNCING: Database shows failed, updating memory status for {transaction_ref}")
                payment_status[transaction_ref] = 'failed'
                status_from_memory = 'failed'
    except Exception as e:
        print(f"❌ Error checking database status: {e}")
    
    # Check if payment is too old (more than 30 minutes)
    if transaction_ref in payment_timestamps:
        payment_age = time.time() - payment_timestamps[transaction_ref]
        if payment_age > 1800 and status_from_memory == 'pending':  # 30 minutes
            payment_status[transaction_ref] = 'timeout'
            status_from_memory = 'timeout'
            print(f"⏰ Payment timeout: {transaction_ref}")
    
    print(f"📊 Payment status for {transaction_ref}: {status_from_memory}")
    
    if status_from_memory == 'success':
        # Double-check and update user's paid courses if needed
        try:
            payment_record = mongo.db.payments.find_one({'transaction_ref': transaction_ref})
            if not payment_record:
                for p in mock_payments:
                    if p['transaction_ref'] == transaction_ref:
                        payment_record = p
                        break
            
            if payment_record:
                user_id = payment_record['user_id']
                course_type = payment_record['course_type']
                
                # Verify and add course to user's paid courses
                try:
                    result = mongo.db.users.update_one(
                        {'_id': ObjectId(user_id) if not user_id.startswith('mock') else user_id},
                        {'$addToSet': {'paid_courses': course_type}}
                    )
                    if result.modified_count > 0:
                        print(f"✅ User {user_id} granted access to {course_type}")
                    else:
                        print(f"ℹ️ User {user_id} already has access to {course_type}")
                except Exception as e:
                    print(f"❌ User update error: {e}")
                    for user in mock_users:
                        if str(user['_id']) == user_id:
                            if 'paid_courses' not in user:
                                user['paid_courses'] = []
                            if course_type not in user['paid_courses']:
                                user['paid_courses'].append(course_type)
                            break
            
        except Exception as e:
            print(f"❌ Payment success handling error: {e}")
        
        return jsonify({'status': 'success'})
    elif status_from_memory == 'failed':
        return jsonify({'status': 'failed'})
    elif status_from_memory == 'timeout':
        return jsonify({'status': 'timeout'})
    
    return jsonify({'status': 'pending'})

@app.route('/callback', methods=['POST'])
def mpesa_callback():
    """M-Pesa callback endpoint - ONLY PROCESSES REAL MPESA CALLBACKS"""
    callback_start_time = time.time()
    try:
        callback_data = request.get_json()
        print(f"📨 REAL MPesa callback received at {datetime.now()}")
        print(f"📊 Callback data: {json.dumps(callback_data, indent=2)}")
        
        # Start fast processing in separate thread and respond immediately to MPesa
        process_payment_callback_fast(callback_data)
        
        response_time = round(time.time() - callback_start_time, 2)
        print(f"⚡ CALLBACK RESPONSE: Sent to MPesa in {response_time} seconds")
        
        # Always return success to MPesa immediately
        return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted'})
        
    except Exception as e:
        response_time = round(time.time() - callback_start_time, 2)
        print(f"❌ Callback error: {e}")
        print(f"⚡ CALLBACK RESPONSE: Error response in {response_time} seconds")
        return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted'})

@app.route('/courses')
def courses():
    """Courses page - redirects to external learning platforms"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Check session timeout (1 hour)
    if 'login_time' in session:
        login_time = datetime.fromisoformat(session['login_time'])
        if datetime.now() - login_time > timedelta(hours=1):
            session.clear()
            return redirect(url_for('login', timeout=True))
    
    # Get user data
    try:
        user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
        if not user:
            for u in mock_users:
                if str(u['_id']) == session['user_id']:
                    user = u
                    break
    except Exception as e:
        print(f"User fetch error: {e}")
        user = None
        for u in mock_users:
            if str(u['_id']) == session['user_id']:
                user = u
                break
    
    if not user:
        session.clear()
        return redirect(url_for('login'))
    
    print(f"📚 Courses page for user: {user.get('username')}, paid courses: {user.get('paid_courses', [])}")
    return render_template('courses.html', 
                         user=user, 
                         course_links=COURSE_LINKS,
                         course_prices=COURSE_PRICES)

@app.route('/check_session')
def check_session():
    """Check if session is still valid (AJAX endpoint)"""
    if 'user_id' not in session:
        return jsonify({'valid': False})
    
    if 'login_time' in session:
        login_time = datetime.fromisoformat(session['login_time'])
        if datetime.now() - login_time > timedelta(hours=1):
            session.clear()
            return jsonify({'valid': False})
    
    return jsonify({'valid': True})

@app.route('/test-db')
def test_db():
    """Test database connection"""
    try:
        mongo.db.command('ping')
        return "✅ Database connected successfully!"
    except Exception as e:
        return f"❌ Database connection failed: {e}"

@app.route('/test-mpesa')
def test_mpesa():
    """Test MPesa token generation"""
    token = get_mpesa_access_token()
    if token:
        return f"✅ MPesa token obtained successfully: {token[:50]}..."
    else:
        return "❌ Failed to get MPesa token"

@app.route('/debug/payments')
def debug_payments():
    """Debug endpoint to see current payment status"""
    current_time = time.time()
    payment_details = {}
    
    for ref, status in payment_status.items():
        age = current_time - payment_timestamps.get(ref, current_time)
        payment_details[ref] = {
            'status': status,
            'age_seconds': round(age, 2),
            'age_minutes': round(age / 60, 2),
            'timestamp': payment_timestamps.get(ref, 0)
        }
    
    return jsonify({
        'payment_status': payment_details,
        'total_pending_payments': len([v for v in payment_status.values() if v == 'pending']),
        'total_successful_payments': len([v for v in payment_status.values() if v == 'success']),
        'total_failed_payments': len([v for v in payment_status.values() if v == 'failed']),
        'callback_url': MPESA_CALLBACK_URL,
        'app_url': 'https://web-development-6fdl.onrender.com',
        'course_prices': COURSE_PRICES
    })

@app.route('/force-complete/<transaction_ref>')
def force_complete_payment(transaction_ref):
    """Force complete a payment for testing - use this to fix stuck payments"""
    try:
        # Update database
        result = mongo.db.payments.update_one(
            {'transaction_ref': transaction_ref},
            {'$set': {
                'status': 'completed', 
                'mpesa_receipt': 'FORCED_COMPLETE',
                'completed_at': datetime.now()
            }}
        )
        
        if result.modified_count > 0:
            # Update memory status
            payment_status[transaction_ref] = 'success'
            
            # Update user's courses
            payment_record = mongo.db.payments.find_one({'transaction_ref': transaction_ref})
            if payment_record:
                user_id = payment_record['user_id']
                course_type = payment_record['course_type']
                
                mongo.db.users.update_one(
                    {'_id': ObjectId(user_id)},
                    {'$addToSet': {'paid_courses': course_type}}
                )
            
            return f"✅ Payment {transaction_ref} force-completed successfully"
        else:
            return f"❌ Payment {transaction_ref} not found"
    except Exception as e:
        return f"❌ Error force-completing payment: {e}"

ADMIN_EMAILS = os.getenv('ADMIN_EMAILS', 'admin@devzencreations.com').split(',')
print(f"🔧 Admin emails: {ADMIN_EMAILS}")

# Admin decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        # Get current user
        try:
            user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
            if not user:
                for u in mock_users:
                    if str(u['_id']) == session['user_id']:
                        user = u
                        break
        except Exception as e:
            print(f"Admin check error: {e}")
            return redirect(url_for('login'))
        
        # Check if user is admin
        if user and user.get('email') in ADMIN_EMAILS:
            return f(*args, **kwargs)
        else:
            return "Access denied: Admin privileges required", 403
    return decorated_function

# Add these new routes after your existing routes

@app.route('/admin')
@admin_required
def admin_dashboard():
    """Admin dashboard"""
    try:
        # Get statistics
        total_users = mongo.db.users.count_documents({})
        total_payments = mongo.db.payments.count_documents({})
        successful_payments = mongo.db.payments.count_documents({'status': 'completed'})
        pending_payments = mongo.db.payments.count_documents({'status': 'pending'})
        
        # Get recent users
        recent_users = list(mongo.db.users.find().sort('created_at', -1).limit(10))
        
        # Get recent payments
        recent_payments = list(mongo.db.payments.find().sort('created_at', -1).limit(10))
        
        # Course statistics
        course_stats = {}
        for course_type in COURSE_PRICES.keys():
            course_count = mongo.db.payments.count_documents({
                'course_type': course_type, 
                'status': 'completed'
            })
            course_stats[course_type] = course_count
        
    except Exception as e:
        print(f"Admin dashboard error: {e}")
        total_users = len(mock_users)
        total_payments = len(mock_payments)
        successful_payments = len([p for p in mock_payments if p.get('status') == 'completed'])
        pending_payments = len([p for p in mock_payments if p.get('status') == 'pending'])
        recent_users = mock_users[-10:] if mock_users else []
        recent_payments = mock_payments[-10:] if mock_payments else []
        course_stats = {}
    
    return render_template('admin_dashboard.html',
                         total_users=total_users,
                         total_payments=total_payments,
                         successful_payments=successful_payments,
                         pending_payments=pending_payments,
                         recent_users=recent_users,
                         recent_payments=recent_payments,
                         course_stats=course_stats,
                         course_descriptions=COURSE_DESCRIPTIONS)

@app.route('/admin/users')
@admin_required
def admin_users():
    """Admin users management"""
    try:
        users = list(mongo.db.users.find().sort('created_at', -1))
    except Exception as e:
        print(f"Admin users error: {e}")
        users = mock_users
    
    return render_template('admin_users.html', users=users)

@app.route('/admin/payments')
@admin_required
def admin_payments():
    """Admin payments management"""
    try:
        payments = list(mongo.db.payments.find().sort('created_at', -1))
        # Join with users to get user details
        for payment in payments:
            try:
                user = mongo.db.users.find_one({'_id': ObjectId(payment['user_id'])})
                if user:
                    payment['user_email'] = user.get('email', 'Unknown')
                    payment['user_name'] = user.get('username', 'Unknown')
                else:
                    payment['user_email'] = 'User not found'
                    payment['user_name'] = 'User not found'
            except:
                payment['user_email'] = 'Invalid user ID'
                payment['user_name'] = 'Invalid user ID'
    except Exception as e:
        print(f"Admin payments error: {e}")
        payments = mock_payments
        for payment in payments:
            payment['user_email'] = 'Mock user'
            payment['user_name'] = 'Mock user'
    
    return render_template('admin_payments.html', payments=payments, course_descriptions=COURSE_DESCRIPTIONS)

@app.route('/admin/user/<user_id>')
@admin_required
def admin_user_detail(user_id):
    """Admin user detail view"""
    try:
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user:
            for u in mock_users:
                if str(u['_id']) == user_id:
                    user = u
                    break
    except Exception as e:
        print(f"Admin user detail error: {e}")
        user = None
    
    if not user:
        return "User not found", 404
    
    # Get user's payments
    try:
        user_payments = list(mongo.db.payments.find({'user_id': user_id}).sort('created_at', -1))
    except Exception as e:
        print(f"User payments error: {e}")
        user_payments = [p for p in mock_payments if p.get('user_id') == user_id]
    
    return render_template('admin_user_detail.html', user=user, payments=user_payments, course_descriptions=COURSE_DESCRIPTIONS)

@app.route('/admin/toggle-user/<user_id>', methods=['POST'])
@admin_required
def admin_toggle_user(user_id):
    """Toggle user active status"""
    try:
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if user:
            new_status = not user.get('is_active', True)
            mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': {'is_active': new_status}}
            )
            return jsonify({'success': True, 'is_active': new_status})
    except Exception as e:
        print(f"Toggle user error: {e}")
    
    return jsonify({'success': False, 'error': 'Failed to update user'})

@app.route('/admin/delete-user/<user_id>', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    """Delete user (admin only)"""
    try:
        # Don't allow admin to delete themselves
        current_user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
        if current_user and str(current_user['_id']) == user_id:
            return jsonify({'success': False, 'error': 'Cannot delete your own account'})
        
        result = mongo.db.users.delete_one({'_id': ObjectId(user_id)})
        if result.deleted_count > 0:
            # Also delete user's payments
            mongo.db.payments.delete_many({'user_id': user_id})
            return jsonify({'success': True})
    except Exception as e:
        print(f"Delete user error: {e}")
    
    return jsonify({'success': False, 'error': 'Failed to delete user'})


@app.route('/test-callback', methods=['GET', 'POST'])
def test_callback():
    """Test if callback URL is accessible"""
    return jsonify({
        'message': 'Callback URL is accessible',
        'timestamp': datetime.now().isoformat(),
        'method': request.method,
        'data_received': request.get_json() if request.method == 'POST' else None,
        'app_url': 'https://web-development-6fdl.onrender.com',
        'callback_url': MPESA_CALLBACK_URL
    })

@app.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'database': 'connected' if mongo.db else 'disconnected',
        'mpesa_token': 'available' if get_mpesa_access_token() else 'unavailable',
        'course_prices': COURSE_PRICES
    })

if __name__ == '__main__':
    print("🚀 Starting application with environment variable configuration...")
    print(f"🔧 Loaded configuration:")
    print(f"   - MongoDB: {'✅ Connected' if mongo.db is not None else '❌ Disconnected'}")
    print(f"   - MPesa: {'✅ Configured' if MPESA_CONSUMER_KEY else '❌ Not configured'}")
    print(f"   - Email: {'✅ Configured' if SMTP_EMAIL else '❌ Not configured'}")
    print(f"💰 Course Prices: {COURSE_PRICES}")
    print(f"📞 Callback URL: {MPESA_CALLBACK_URL}")
    print(f"🌐 App URL: https://web-development-6fdl.onrender.com")
    
    if MPESA_SHORTCODE:
        print(f"🏢 Business Shortcode: {MPESA_SHORTCODE}")
    else:
        print("🏢 Business Shortcode: ❌ Not configured")
    
    print("⚡ REAL MPesa CALLBACK PROCESSING ONLY - No simulation fallback")
    
    app.run(debug=True, port=5000, host='0.0.0.0')