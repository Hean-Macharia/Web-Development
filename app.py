from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_pymongo import PyMongo
from bson.objectid import ObjectId
from datetime import datetime, timedelta
import requests
import base64
import json
import time
import threading
import os
import re
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-in-production'

# MongoDB configuration with error handling
try:
    app.config["MONGO_URI"] = "mongodb+srv://iconichean:1Loye8PM3YwlV5h4@cluster0.meufk73.mongodb.net/webdev_courses?retryWrites=true&w=majority"
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

# M-Pesa Daraja API credentials (PRODUCTION)
MPESA_CONSUMER_KEY = 'xueqgztGna3VENZaV7c6pXC34uk7LsDxA4dnIjG2n3OV167d'
MPESA_CONSUMER_SECRET = 'XpbH6z5QRz4unhk6XDg83G2n1p796Fd9EUvqs0tEDE3TsZZeYauJ2AApBb0SoMiL'
MPESA_PASSKEY = 'a3d842c161dc6617ac99f9e6d250fc1583584e29c1cae2123d3d9f4db94790dc'
MPESA_SHORTCODE = '4185095'
MPESA_CALLBACK_URL = 'https://kuccps-courses-px6s.onrender.com/callback'

# Payment settings - REAL MPESA
PAYMENT_AMOUNT = 1  # 1 KSH for testing, change to 500 for production
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
                        
                        # IMMEDIATELY update payment status
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
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration"""
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        index_number = request.form['index_number']
        phone = request.form['phone']
        password = request.form['password']
        
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
            print(f"✅ User logged in: {email}")
            return redirect(url_for('courses'))
        else:
            return render_template('login.html', error="Invalid credentials")
    
    return render_template('login.html')

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
    
    if request.method == 'POST':
        phone = request.form['phone']
        amount = PAYMENT_AMOUNT
        
        # Validate phone number format
        if not phone.startswith('254') or len(phone) != 12:
            return render_template('payment.html', course_type=course_type, 
                                 error="Invalid phone number. Use format: 2547XXXXXXXX")
        
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
            return render_template('payment.html', course_type=course_type, error=error_msg)
    
    return render_template('payment.html', course_type=course_type)

@app.route('/payment/wait/<transaction_ref>')
def payment_wait(transaction_ref):
    """Payment waiting page"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    print(f"🔄 Payment wait page for: {transaction_ref}")
    return render_template('payment_wait.html', transaction_ref=transaction_ref)

@app.route('/payment/status/<transaction_ref>')
def payment_status_check(transaction_ref):
    """Check payment status (AJAX endpoint)"""
    print(f"🔄 Checking payment status for: {transaction_ref}")
    
    # Check if payment is too old (more than 30 minutes)
    if transaction_ref in payment_timestamps:
        payment_age = time.time() - payment_timestamps[transaction_ref]
        if payment_age > 1800:  # 30 minutes
            payment_status[transaction_ref] = 'timeout'
            print(f"⏰ Payment timeout: {transaction_ref}")
    
    if transaction_ref in payment_status:
        status = payment_status[transaction_ref]
        print(f"📊 Payment status for {transaction_ref}: {status}")
        
        if status == 'success':
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
        elif status == 'failed':
            return jsonify({'status': 'failed'})
        elif status == 'timeout':
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
    return render_template('courses.html', user=user, course_links=COURSE_LINKS)

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
        'callback_url_accessible': 'Check if URL is publicly accessible'
    })

@app.route('/test-callback', methods=['GET', 'POST'])
def test_callback():
    """Test if callback URL is accessible"""
    return jsonify({
        'message': 'Callback URL is accessible',
        'timestamp': datetime.now().isoformat(),
        'method': request.method,
        'data_received': request.get_json() if request.method == 'POST' else None
    })

if __name__ == '__main__':
    print("🚀 Starting application with REAL MPesa integration...")
    print(f"💰 Payment amount: KSh {PAYMENT_AMOUNT}")
    print(f"📞 Callback URL: {MPESA_CALLBACK_URL}")
    print(f"🏢 Business Shortcode: {MPESA_SHORTCODE}")
    print("⚡ REAL MPesa CALLBACK PROCESSING ONLY - No simulation fallback")
    print("⏳ Payments will only complete when MPesa sends callback with receipt")
    app.run(debug=True, port=5000, host='0.0.0.0')