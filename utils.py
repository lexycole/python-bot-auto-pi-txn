"""
Utility functions for interacting with the Stellar network for Pi transactions
"""
import logging
from stellar_sdk import Server, Keypair, TransactionBuilder, Asset, Network

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Constants
MAINNET_URL = "https://api.mainnet.minepi.com"
TESTNET_URL = "https://api.testnet.minepi.com"

# Default Pi wallet key (can be overridden by user input)
DEFAULT_SENDER_SECRET = ""

# Pi asset is the native asset on the Pi network
PI_ASSET = Asset.native()

# utils.py
def get_network_passphrase(network: str) -> str:
    if network == "mainnet":
        return "Pi Network"
    else:                       
        return "Pi Testnet"  



def get_horizon_url(network):
    """Get the correct Horizon URL based on network"""
    if network == "mainnet":
        return MAINNET_URL
    else:
        return TESTNET_URL

def validate_stellar_address(address):
    """Validate a Stellar public key address format"""
    try:
        Keypair.from_public_key(address)
        return True
    except Exception:
        return False

def get_account_balance(account_id, network="mainnet"):
    """Get account Pi balance"""
    server = Server(horizon_url=get_horizon_url(network))
    
    try:
        account = server.accounts().account_id(account_id).call()
        # Find the native asset (Pi) balance
        balance = next((b['balance'] for b in account['balances'] if b['asset_type'] == 'native'), '0')
        return balance
    except Exception as e:
        logger.error(f"Error fetching balance: {str(e)}")
        raise Exception(f"Could not fetch balance: {str(e)}")

def verify_transaction(tx_hash, network="mainnet"):
    """Verify if a transaction is actually completed on the Pi Network"""
    if tx_hash == "Unknown" or tx_hash == "Failed" or not tx_hash:
        return False
        
    server = Server(horizon_url=get_horizon_url(network))
    
    try:
        # Try to retrieve the transaction details
        tx_details = server.transactions().transaction(tx_hash).call()
        
        # Check if it has the successful flag (handle different response formats)
        if isinstance(tx_details, dict):
            return tx_details.get('successful', False)
        elif hasattr(tx_details, 'successful'):
            return bool(getattr(tx_details, 'successful', False))
        elif tx_details:  # If we got a response but can't determine success, assume it exists
            return True
        else:
            logger.warning(f"Transaction {tx_hash} exists but is not marked as successful")
            return False
    except Exception as e:
        logger.error(f"Error verifying transaction {tx_hash}: {str(e)}")
        return False

def send_transaction(sender_secret, sender_public, receiver_address, amount="1", network="mainnet"):
    """Send Pi transaction on the network"""
    server = Server(horizon_url=get_horizon_url(network))
    network_passphrase = get_network_passphrase(network)
    
    try:
        # Create keypair from secret
        sender_keypair = Keypair.from_secret(sender_secret)
        
        # Verify that the public key matches the keypair
        if sender_keypair.public_key != sender_public:
            raise Exception("Public key doesn't match the provided secret key")
        
        # Load account details
        source_account = server.load_account(sender_public)
        
        # Convert amount to string if it's not already
        if not isinstance(amount, str):
            amount = str(amount)
            
        # Ensure proper decimal format for the Pi amount
        if '.' not in amount:
            amount = f"{amount}.0"
        
        # Build the transaction with Pi Network specific settings
        transaction = (
            TransactionBuilder(
                source_account=source_account,
                network_passphrase=network_passphrase,
                base_fee=100000  # 0.01 Pi (in stroops, 1 Pi = 10,000,000 stroops)
            )
            .append_payment_op(
                destination=receiver_address,
                asset=PI_ASSET,
                amount=amount
            )
            .set_timeout(180)  # Extended timeout for Pi Network congestion
            # Add a memo to identify our transaction
            .add_text_memo("Pi Auto Sender")
            .build()
        )
        
        # Log exact transaction XDR for debugging
        logger.debug(f"Transaction XDR: {transaction.to_xdr()}")
        
        # Sign the transaction
        transaction.sign(sender_keypair)

        
        # Log transaction details before submission for debugging
        logger.debug(f"Submitting transaction: {amount} PI from {sender_public} to {receiver_address}")
        
        try:
            # Submit the transaction
            response = server.submit_transaction(transaction)
            
            # Properly handle response - stellar-sdk returns different response objects depending on version
            if isinstance(response, dict):
                # Dictionary-style response
                tx_hash = response.get('hash', 'Unknown')
                ledger = response.get('ledger', 'Unknown')
                successful = response.get('successful', True)
            elif hasattr(response, 'hash'):
                # Object-style response
                tx_hash = getattr(response, 'hash', 'Unknown')
                ledger = getattr(response, 'ledger', 'Unknown')
                successful = getattr(response, 'successful', True)
            else:
                # Fallback for unexpected response type
                tx_hash = str(response)
                ledger = 'Unknown'
                successful = True
                
            logger.info(f"Transaction successful: hash={tx_hash}, ledger={ledger}")
            
            return {
                "hash": tx_hash,
                "ledger": ledger,
                "successful": successful,
                "status": "Success"
            }
            
        except Exception as submit_error:
            # Special handling for submission errors
            error_msg = str(submit_error)
            logger.error(f"Transaction submission error: {error_msg}")
            
            # Check for common error patterns in the Pi Network response
            if "op_underfunded" in error_msg:
                raise Exception("Insufficient funds for this transaction")
            elif "tx_bad_seq" in error_msg:
                raise Exception("Invalid sequence number. Please try again")
            elif "tx_failed" in error_msg:
                raise Exception("Transaction failed. The Pi Network rejected the operation")
            elif "op_malformed" in error_msg:
                raise Exception("Transaction was malformed. Check the amount format")
            elif "too_many_operations" in error_msg:
                raise Exception("Too many operations in this transaction")
            elif "tx_busy" in error_msg:
                # Pi network might be congested
                raise Exception("Pi Network is busy. Try again later")
            elif "signature" in error_msg.lower() or "sign" in error_msg.lower():
                raise Exception("Signature validation failed. Check your private key")
            else:
                # Log the full error for debugging purposes
                logger.debug(f"Full Pi Network error: {repr(submit_error)}")
                raise Exception(f"Transaction submission failed: {error_msg}")
        
    except Exception as e:
        logger.error(f"Transaction error: {str(e)}")
        raise Exception(f"Transaction failed: {str(e)}")
