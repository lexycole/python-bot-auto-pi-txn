import os
import logging
import time
import threading
import queue
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session
from stellar_sdk import Keypair
from dotenv import load_dotenv
from utils import get_account_balance, send_transaction, validate_stellar_address, verify_transaction

load_dotenv()
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "pi_network_secret")

DEFAULT_SENDER_SECRET = os.getenv("PI_SENDER_SECRET")
DEFAULT_SENDER_PUBLIC = os.getenv("PI_SENDER_PUBLIC")

if not DEFAULT_SENDER_SECRET or not DEFAULT_SENDER_PUBLIC:
    raise RuntimeError("Add PI_SENDER_SECRET and PI_SENDER_PUBLIC to your .env file")


# Global variables
transaction_thread = None
RUNNING = False
transaction_history = []
MAX_HISTORY = 50  # Maximum number of transactions to keep in history

# Performance metrics
transaction_timings = []
MAX_TIMING_SAMPLES = 100  # Maximum number of timing samples to keep

# Transaction timing settings - DEFAULT TO 1ms INSTEAD OF 5000ms
TRANSACTION_INTERVAL_MS = 100  # Default 1 millisecond between transactions (was 5000)
MINIMUM_INTERVAL_MS = 1  # Absolute minimum interval
SCHEDULED_TIME = None  # Default to no scheduled start time

# Transaction queue system to manage high-frequency requests
tx_queue = queue.Queue()
queue_processor_thread = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/setup', methods=['POST'])
def setup():
    try:
        # Safely get JSON data or use empty dict if None
        if request.is_json:
            data = request.get_json()
        else:
            data = {}
            
        # Extract data with defaults
        sender_secret = data.get('sender_secret', DEFAULT_SENDER_SECRET)
        sender_public = data.get('sender_public', '')
        receiver_address = data.get('receiver_address', '')
        amount = data.get('amount', '1')
        network = data.get('network', 'mainnet')
        
        # Validate input data
        if not sender_public or not receiver_address:
            return jsonify({"success": False, "message": "Sender public key and receiver address are required"}), 400
        
        # Use default secret key if not provided
        using_default_key = False
        if not sender_secret or sender_secret == DEFAULT_SENDER_SECRET:
            sender_secret = DEFAULT_SENDER_SECRET
            using_default_key = True
            logger.info("Using default sender secret key")
        
        # Validate stellar addresses
        if not validate_stellar_address(sender_public) or not validate_stellar_address(receiver_address):
            return jsonify({"success": False, "message": "Invalid Pi wallet address format"}), 400
        
        # Check if private key matches public key
        try:
            # This will raise an exception if the keys don't match
            keypair = Keypair.from_secret(sender_secret)
            derived_public_key = keypair.public_key
            
            if derived_public_key != sender_public:
                logger.warning("Provided public key doesn't match the one derived from secret key")
                return jsonify({
                    "success": False,
                    "message": "Private key doesn't match the provided public address"
                }), 400
                
        except Exception as e:
            logger.error(f"Error validating key pair: {str(e)}")
            return jsonify({
                "success": False,
                "message": f"Invalid private key format: {str(e)}"
            }), 400
            
        # Store in session
        session['sender_secret'] = sender_secret
        session['sender_public'] = sender_public
        session['receiver_address'] = receiver_address
        session['amount'] = amount
        session['network'] = network
        
        # Get initial balance
        try:
            balance = get_account_balance(sender_public, network)
            message = "Wallet connected successfully"
            if using_default_key:
                message += f" (Using default private key with {balance} PI balance)"
            else:
                message += f" (Your private key with {balance} PI balance)"
                
            return jsonify({
                "success": True, 
                "message": message, 
                "balance": balance,
                "using_default_key": using_default_key
            })
        except Exception as e:
            logger.error(f"Error fetching balance: {str(e)}")
            return jsonify({
                "success": False, 
                "message": f"Error connecting to Pi Network: {str(e)}"
            }), 500
            
    except Exception as e:
        logger.error(f"Setup error: {str(e)}")
        return jsonify({"success": False, "message": f"An error occurred: {str(e)}"}), 500

@app.route('/api/balance', methods=['GET'])
def get_balance():
    try:
        sender_public = session.get('sender_public')
        network = session.get('network', 'mainnet')
        
        if not sender_public:
            return jsonify({"success": False, "message": "Wallet not connected"}), 400
            
        balance = get_account_balance(sender_public, network)
        return jsonify({"success": True, "balance": balance})
    except Exception as e:
        logger.error(f"Balance fetch error: {str(e)}")
        return jsonify({"success": False, "message": f"Error fetching balance: {str(e)}"}), 500

def high_precision_sleep(sleep_time_seconds):
    """
    Ultra high precision sleep function using busy-wait for microsecond accuracy
    Optimized for 1ms transaction intervals
    - For very short sleeps (< 5ms), uses pure busy-waiting for maximum precision
    - For longer sleeps, uses a hybrid approach for efficiency while maintaining precision
    """
    if sleep_time_seconds <= 0:
        return
        
    # For extremely short sleeps (1ms range), use pure busy-waiting for maximum precision
    if sleep_time_seconds <= 0.005:  # <= 5ms
        start_time = time.time()
        while time.time() - start_time < sleep_time_seconds:
            pass  # Pure busy-wait for ultra-high precision
        return
        
    # For medium sleeps (5ms-50ms), use a finer-grained hybrid approach
    if sleep_time_seconds <= 0.05:  # <= 50ms
        # Sleep for 50% of the time
        time.sleep(sleep_time_seconds * 0.5)
        # Busy-wait for the remainder with higher precision
        remaining_time = sleep_time_seconds * 0.5
        start_time = time.time()
        while time.time() - start_time < remaining_time:
            pass
        return
        
    # For longer sleeps, use regular sleep for most of it with a small busy-wait buffer
    time.sleep(sleep_time_seconds - 0.003)  # Sleep all but 3ms
    
    # Busy-wait for the last 3ms for precision
    start_time = time.time()
    end_time = start_time + 0.003
    while time.time() < end_time:
        pass  # Busy-wait for remaining time

def process_transaction(sender_secret, sender_public, receiver_address, amount, network):
    """Process a single transaction and return the result with timing information"""
    start_time = time.time()
    
    try:
        # Check balance before transaction
        try:
            balance_before = get_account_balance(sender_public, network)
            logger.debug(f"Balance before transaction: {balance_before} PI")
        except Exception as balance_error:
            logger.warning(f"Could not fetch balance before transaction: {str(balance_error)}")
            balance_before = "Unknown"
        
        # Ensure amount is a string for consistent handling
        if not isinstance(amount, str):
            amount = str(amount)
        
        # Send transaction with improved error handling
        transaction_result = send_transaction(
            sender_secret=sender_secret,
            sender_public=sender_public,
            receiver_address=receiver_address,
            amount=amount,
            network=network
        )
        
        # Extract transaction details
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        tx_hash = transaction_result.get('hash', 'Unknown')
        ledger = transaction_result.get('ledger', 'Unknown')
        status = transaction_result.get('status', 'Success')
        
        # Verify transaction on the network (with retry)
        verification_status = False
        for retry in range(2):  # Reduced retries for high frequency
            verification_status = verify_transaction(tx_hash, network)
            if verification_status:
                break
            time.sleep(0.05)  # Short delay between retries
        
        # Check balance after transaction
        balance_after = "Unknown"  # Initialize with default value
        try:
            balance_after = get_account_balance(sender_public, network)
            logger.debug(f"Balance after transaction: {balance_after} PI")
            
            # Calculate balance change
            if balance_before != "Unknown" and balance_after != "Unknown":
                try:
                    before_val = float(balance_before)
                    after_val = float(balance_after)
                    balance_change = before_val - after_val
                    
                    # If balance changed, transaction was successful
                    if balance_change > 0:
                        verification_status = True
                        status = "Success"
                        logger.info(f"Verified balance change: {balance_change} PI deducted")
                    else:
                        logger.warning(f"No balance change detected: before={balance_before}, after={balance_after}")
                        if not verification_status:
                            status = "Pending" 
                except Exception as calc_error:
                    logger.warning(f"Could not calculate balance change: {str(calc_error)}")
        except Exception as balance_error:
            logger.warning(f"Could not fetch balance after transaction: {str(balance_error)}")
        
        # Set final status based on verification
        if verification_status:
            status = "Success"
        elif status == "Success":  # If thought successful but not verified
            status = "Pending"
        
        # Calculate actual transaction processing time
        end_time = time.time()
        processing_time_ms = (end_time - start_time) * 1000  # Convert to ms
        
        # Ensure processing_time_ms is a string to avoid concatenation errors
        processing_time_ms_str = str(round(processing_time_ms, 2))
        
        # Transaction info with all numeric fields converted to strings
        transaction_info = {
            "timestamp": timestamp,
            "amount": amount,
            "hash": tx_hash,
            "status": status,
            "ledger": str(ledger),
            "balance_before": str(balance_before),
            "balance_after": str(balance_after),
            "verified": verification_status,
            "details": transaction_result,
            "processing_time_ms": processing_time_ms_str
        }
        
        return True, transaction_info
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Payment error: {error_msg}")
        
        # Calculate processing time even for errors
        end_time = time.time()
        processing_time_ms = (end_time - start_time) * 1000
        
        # Record failed transaction with more details - ensure all values are strings
        transaction_info = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "amount": str(amount),
            "hash": "Failed",
            "status": "Error",
            "error": error_msg,
            "balance_before": "Unknown",
            "balance_after": "Unknown",
            "verified": False,
            "processing_time_ms": str(round(processing_time_ms, 2))
        }
        
        return False, transaction_info

def transaction_loop_with_context(sender_secret, sender_public, receiver_address, amount, network):
    """
    Ultra-optimized transaction loop function with precise timing control that works outside Flask request context
    Uses a high-precision timing approach to maintain accurate transaction intervals at 1ms
    All parameters are passed directly to avoid Flask session dependency
    """
    global RUNNING, transaction_history, transaction_timings
    
    try:
        RUNNING = True
        logger.info(f"Starting ultra high-frequency transaction loop with direct parameters")
        
        # Get transaction interval in seconds (convert from ms)
        transaction_interval_sec = max(float(TRANSACTION_INTERVAL_MS) / 1000.0, float(MINIMUM_INTERVAL_MS) / 1000.0)
        
        # Handle scheduled start if provided
        if SCHEDULED_TIME:
            try:
                # Parse scheduled time
                scheduled_datetime = datetime.fromisoformat(SCHEDULED_TIME.replace('Z', '+00:00'))
                
                # Calculate wait time until scheduled start
                now = datetime.now(scheduled_datetime.tzinfo)
                wait_seconds = (scheduled_datetime - now).total_seconds()
                
                if wait_seconds > 0:
                    logger.info(f"Waiting {wait_seconds:.2f} seconds until scheduled start time: {SCHEDULED_TIME}")
                    # Sleep until scheduled time
                    time.sleep(wait_seconds)
                    logger.info("Scheduled time reached, starting transactions now")
                else:
                    logger.info("Scheduled time is in the past, starting immediately")
            except Exception as e:
                logger.warning(f"Error parsing scheduled time, starting immediately: {str(e)}")
                
        # Initialize timing tracking variables with nanosecond precision if possible
        try:
            # Try to use high-resolution performance counter if available
            next_transaction_time = time.perf_counter()
        except:
            # Fall back to standard time
            next_transaction_time = time.time()
        
        # Pre-transaction delay of 10ms to allow system to stabilize
        time.sleep(0.01)
        logger.info(f"Starting high-frequency transaction loop with interval: {transaction_interval_sec*1000:.2f}ms")
        
        # Main transaction loop with ultra-precise timing for 1ms intervals
        transaction_count = 0
        while RUNNING:
            try:
                # Use high-precision performance counter when available
                try:
                    current_time = time.perf_counter()
                except:
                    current_time = time.time()
                    
                time_until_next = next_transaction_time - current_time
                
                # Special handling for 1ms intervals - maximum precision mode
                if transaction_interval_sec <= 0.002:  # 2ms or less
                    if time_until_next < 0:
                        # We're behind - log only occasionally to reduce overhead
                        if transaction_count % 100 == 0:
                            drift_ms = -time_until_next * 1000
                            logger.warning(f"Ultra-high frequency drift: {drift_ms:.3f}ms behind schedule")
                        # Don't reset time, try to catch up instead for 1ms intervals
                        # This allows the system to recover from momentary delays
                    else:
                        # For 1ms intervals, use pure busy-waiting for maximum precision
                        # This avoids the overhead of function calls for ultra-short waits
                        while time.perf_counter() < next_transaction_time:
                            pass  # Direct busy-wait loop
                else:
                    # Standard handling for longer intervals
                    if time_until_next < 0:
                        drift_ms = -time_until_next * 1000
                        logger.warning(f"Transaction timing drift: {drift_ms:.2f}ms behind schedule")
                        # Reset timing to avoid cumulative drift for longer intervals
                        next_transaction_time = current_time
                    else:
                        # Use our optimized high-precision sleep function
                        high_precision_sleep(time_until_next)
                
                # Record the actual execution time with highest available precision
                try:
                    actual_execution_time = time.perf_counter()
                except:
                    actual_execution_time = time.time()
                    
                execution_drift_ms = (actual_execution_time - next_transaction_time) * 1000
                transaction_count += 1
                
                # Process the transaction
                try:
                    # Ensure amount is a string for consistent handling
                    if not isinstance(amount, str):
                        amount = str(amount)
                        
                    success, transaction_info = process_transaction(
                        sender_secret, sender_public, receiver_address, amount, network
                    )
                    
                    # Double-check all numeric fields are strings to avoid concatenation errors
                    for field in ['processing_time_ms', 'drift_ms']:
                        if field in transaction_info and not isinstance(transaction_info[field], str):
                            transaction_info[field] = str(transaction_info[field])
                except Exception as process_error:
                    logger.error(f"Critical error during transaction processing: {str(process_error)}")
                    success = False
                    transaction_info = {
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                        "amount": str(amount),
                        "hash": "Failed",
                        "status": "Error",
                        "error": f"Critical transaction error: {str(process_error)}",
                        "balance_before": "Unknown",
                        "balance_after": "Unknown",
                        "verified": False,
                        "processing_time_ms": "0",
                        "drift_ms": "0"
                    }
                
                # Add to transaction history
                transaction_history.append(transaction_info)
                
                # Limit history size
                if len(transaction_history) > MAX_HISTORY:
                    transaction_history.pop(0)
                
                # Track timing statistics - ensure all values are properly formatted as strings
                # Create a copy of transaction_info with all numeric values converted to strings
                # This prevents type concatenation errors when working with the data
                safe_info = {}
                processing_time = "0"
                
                # Get processing time or use default
                if "processing_time_ms" in transaction_info:
                    if isinstance(transaction_info["processing_time_ms"], str):
                        processing_time = transaction_info["processing_time_ms"]
                    else:
                        processing_time = str(transaction_info["processing_time_ms"])
                
                # Add properly formatted timing statistics
                transaction_timings.append({
                    "scheduled_time": str(next_transaction_time),
                    "actual_time": str(actual_execution_time),
                    "drift_ms": str(round(execution_drift_ms, 3)),
                    "processing_time_ms": processing_time
                })
                
                # Limit timing samples
                if len(transaction_timings) > MAX_TIMING_SAMPLES:
                    transaction_timings.pop(0)
                
                # Calculate the next transaction time with ultra-precision
                # For 1ms intervals, we need special handling to prevent timing drift
                if transaction_interval_sec <= 0.002:  # 2ms or less
                    # Use absolute timing based on start time to prevent cumulative drift
                    # This ensures each transaction happens exactly at the planned interval
                    # regardless of how long each transaction processing took
                    next_transaction_time += transaction_interval_sec
                else:
                    # For longer intervals, add the interval to the current time to prevent long delays
                    # if the system is running behind
                    if time_until_next < 0 and abs(time_until_next) > transaction_interval_sec * 2:
                        # If we're severely behind schedule, reset to avoid massive catchup attempts
                        next_transaction_time = actual_execution_time + transaction_interval_sec
                    else:
                        # Normal case - add interval to previous planned time
                        next_transaction_time += transaction_interval_sec
                
                # Log success or failure
                if success:
                    logger.debug(f"Sent {amount} PI: {transaction_info.get('hash', 'Unknown')}")
                else:
                    logger.warning(f"Transaction failed: {transaction_info.get('error', 'Unknown error')}")
                
            except Exception as e:
                logger.error(f"Error in transaction loop: {str(e)}")
                # Add small delay for error recovery
                time.sleep(0.01)
                # Recalculate next transaction time
                next_transaction_time = time.time() + transaction_interval_sec
                
    except Exception as e:
        logger.error(f"Fatal error in transaction loop: {str(e)}")
        RUNNING = False

@app.route('/api/start', methods=['POST'])
def start():
    global RUNNING, transaction_thread, TRANSACTION_INTERVAL_MS, SCHEDULED_TIME
    
    if RUNNING:
        return jsonify({"success": False, "message": "Transaction bot is already running"})
    
    # Get request data if provided
    data = request.json or {}
    
    # Get saved session values
    sender_secret = session.get('sender_secret')
    sender_public = session.get('sender_public')
    receiver_address = session.get('receiver_address')
    amount = session.get('amount', '1')
    network = session.get('network', 'mainnet')
    
    # Get transaction timing parameters 
    transaction_interval_ms = data.get('transaction_interval', MINIMUM_INTERVAL_MS)  # Default 1 millisecond
    scheduled_time = data.get('scheduled_time')
    
    # Validate interval - enforce minimum
    if transaction_interval_ms < MINIMUM_INTERVAL_MS:
        transaction_interval_ms = MINIMUM_INTERVAL_MS
        
    # Store timing parameters globally for status API
    TRANSACTION_INTERVAL_MS = transaction_interval_ms
    SCHEDULED_TIME = scheduled_time
    
    # Log transaction parameters
    logger.info(f"Starting transaction bot with interval: {transaction_interval_ms}ms")
    if scheduled_time:
        logger.info(f"Scheduled start time: {scheduled_time}")
    
    if not sender_secret or not sender_public or not receiver_address:
        return jsonify({"success": False, "message": "Wallet information not provided. Please connect wallet first."}), 400
    
    # Clear previous transaction history
    global transaction_history, transaction_timings
    transaction_history = []
    transaction_timings = []
    
    # Start transaction thread with direct parameter passing to avoid Flask request context issues
    transaction_thread = threading.Thread(
        target=transaction_loop_with_context,
        args=(sender_secret, sender_public, receiver_address, amount, network)
    )
    transaction_thread.daemon = True
    transaction_thread.start()
    
    return jsonify({
        "success": True,
        "message": f"Transaction bot started with {transaction_interval_ms}ms interval", 
        "transaction_interval_ms": transaction_interval_ms,
        "scheduled_time": scheduled_time or "Immediate"
    })

@app.route('/api/stop', methods=['POST'])
def stop():
    global RUNNING, transaction_thread
    
    if not RUNNING:
        return jsonify({"success": False, "message": "Transaction bot is not running"})
    
    RUNNING = False
    # Allow thread to terminate naturally
    if transaction_thread:
        transaction_thread.join(timeout=2.0)
    
    return jsonify({"success": True, "message": "Transaction bot stopped"})

@app.route('/api/status', methods=['GET'])
def status():
    global RUNNING, transaction_history, transaction_timings
    
    # Calculate performance metrics if we have timing data
    performance_metrics = {}
    if transaction_timings:
        try:
            # Convert values to float before calculation
            drifts = [float(t.get('drift_ms', 0)) for t in transaction_timings]
            processing_times = [float(t.get('processing_time_ms', 0)) for t in transaction_timings]
            
            performance_metrics = {
                "avg_drift_ms": round(sum(drifts) / len(drifts), 2),
                "max_drift_ms": round(max(drifts), 2),
                "min_drift_ms": round(min(drifts), 2),
                "avg_processing_time_ms": round(sum(processing_times) / len(processing_times), 2),
                "max_processing_time_ms": round(max(processing_times), 2),
                "min_processing_time_ms": round(min(processing_times), 2),
                "samples": len(transaction_timings),
                "transaction_interval_ms": TRANSACTION_INTERVAL_MS
            }
        except (ValueError, TypeError) as e:
            logger.error(f"Error calculating performance metrics: {str(e)}")
            # Provide default metrics on error
            performance_metrics = {
                "avg_drift_ms": 0,
                "max_drift_ms": 0,
                "min_drift_ms": 0,
                "avg_processing_time_ms": 0,
                "max_processing_time_ms": 0,
                "min_processing_time_ms": 0,
                "samples": len(transaction_timings),
                "transaction_interval_ms": TRANSACTION_INTERVAL_MS,
                "error": f"Could not calculate metrics: {str(e)}"
            }
    
    return jsonify({
        "running": RUNNING,
        "transaction_count": len(transaction_history),
        "transactions": transaction_history,
        "performance": performance_metrics,
        "transaction_interval_ms": TRANSACTION_INTERVAL_MS,
        "scheduled_time": SCHEDULED_TIME
    })

@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    global transaction_history
    return jsonify({"transactions": transaction_history})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
