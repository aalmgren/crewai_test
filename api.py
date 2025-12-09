"""
Flask API for processing drilling data files
"""
import os
import json
import tempfile
import logging
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from crewai_test import run_analysis_api, format_consolidated_summary_json
from token_tracker import get_current_stats, reset_stats

# Configure logging with custom formatter
log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

class MultilineFormatter(logging.Formatter):
    """Formatter that breaks long messages into multiple lines"""
    def format(self, record):
        # Get the formatted message
        msg = super().format(record)
        
        # If message is very long, try to format it better
        if len(msg) > 200:
            import re
            
            # Special handling for litellm.completion calls
            if 'litellm.completion' in msg:
                # Extract and format parameters
                # Break after function name
                msg = re.sub(r'(litellm\.completion\()', r'\1\n  ', msg)
                
                # Break each parameter on a new line
                msg = re.sub(r',\s+(model=|messages=|temperature=|stop=)', r',\n  \1', msg)
                
                # Format messages array
                msg = re.sub(r"(messages=\[)", r"\1\n    ", msg)
                msg = re.sub(r"(\{'role':)", r"\n      \1", msg)
                msg = re.sub(r"('content':)", r"\n        \1", msg)
                msg = re.sub(r"(\},\s*\{)", r"\1\n      ", msg)
                msg = re.sub(r"(\]\s*,)", r"\1\n  ", msg)
                
                # Break long content strings (but preserve structure)
                # This is tricky, so we'll just ensure lines aren't too long
                lines = msg.split('\n')
                formatted_lines = []
                for line in lines:
                    # If line is still too long, break at safe points
                    if len(line) > 120:
                        # Break at commas, spaces, or other safe points
                        parts = re.split(r'([,;:])', line)
                        current_line = ""
                        for part in parts:
                            if len(current_line + part) > 120 and current_line:
                                formatted_lines.append(current_line.rstrip())
                                current_line = "        " + part  # Indent continuation
                            else:
                                current_line += part
                        if current_line:
                            formatted_lines.append(current_line.rstrip())
                    else:
                        formatted_lines.append(line)
                msg = '\n'.join(formatted_lines)
            else:
                # For other long messages, break at safe points
                if len(msg) > 150:
                    # Break on commas, semicolons, or other separators
                    msg = re.sub(r',\s+', ',\n    ', msg)
                    # Break on opening/closing brackets
                    msg = re.sub(r'(\[|\{)', r'\1\n    ', msg)
                    msg = re.sub(r'(\]|\})', r'\n\1', msg)
        
        return msg

log_filename = os.path.join(log_dir, f"api_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

# Create file handler with custom formatter
file_handler = logging.FileHandler(log_filename, encoding='utf-8')
file_handler.setFormatter(MultilineFormatter('%(asctime)s - %(levelname)s - %(message)s'))

# Create console handler (simpler format for console)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Configure root logger
logging.basicConfig(
    level=logging.DEBUG,
    handlers=[file_handler, console_handler]
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='.', static_url_path='')
# Set maximum upload size to 100MB (for large CSV files)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB

# Enable CORS - allow all origins in development for file:// access
# In production, restrict to specific origins
CORS(app, resources={
    r"/*": {
        "origins": "*",  # Allow all origins (including null for file://)
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    """Process uploaded CSV files"""
    session_id = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    logger.info(f"=== NEW ANALYSIS REQUEST - Session ID: {session_id} ===")
    
    try:
        if 'files' not in request.files:
            logger.warning(f"Session {session_id}: No files provided in request")
            return jsonify({"error": "No files provided"}), 400
        
        files = request.files.getlist('files')
        if not files or files[0].filename == '':
            logger.warning(f"Session {session_id}: No files selected")
            return jsonify({"error": "No files selected"}), 400
        
        file_names = [f.filename for f in files if f.filename.endswith('.csv')]
        logger.info(f"Session {session_id}: Files received: {file_names}")
        
        # Create temporary directory for uploaded files
        with tempfile.TemporaryDirectory() as temp_dir:
            # Save uploaded files
            saved_files = []
            for file in files:
                if file.filename.endswith('.csv'):
                    file_path = os.path.join(temp_dir, file.filename)
                    try:
                        file.save(file_path)
                        saved_files.append(file.filename)
                        logger.info(f"Session {session_id}: Saved file {file.filename}")
                    except Exception as e:
                        logger.error(f"Session {session_id}: Error saving file {file.filename}: {str(e)}")
                        return jsonify({
                            "error": f"Error saving file {file.filename}: {str(e)}",
                            "type": type(e).__name__
                        }), 400
            
            if not saved_files:
                logger.warning(f"Session {session_id}: No CSV files were saved")
                return jsonify({"error": "No CSV files were saved"}), 400
            
            # Run analysis
            try:
                logger.info(f"Session {session_id}: Starting analysis for {len(saved_files)} files")
                results = run_analysis_api(temp_dir, session_id=session_id, logger=logger)
                logger.info(f"Session {session_id}: Analysis completed. Results count: {len(results) if results else 0}")
                
                # Log detailed results
                if results:
                    for r in results:
                        logger.info(f"Session {session_id}: File '{r.get('file', 'unknown')}' - Type result: {str(r.get('type', 'N/A'))[:200]}")
                        logger.info(f"Session {session_id}: File '{r.get('file', 'unknown')}' - Columns result: {str(r.get('columns', 'N/A'))[:500]}")
                else:
                    logger.warning(f"Session {session_id}: Analysis returned empty results")
                    
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                logger.error(f"Session {session_id}: Error during analysis: {str(e)}\n{error_trace}")
                return jsonify({
                    "error": f"Error during analysis: {str(e)}",
                    "type": type(e).__name__,
                    "traceback": error_trace
                }), 500
            
            if not results:
                logger.warning(f"Session {session_id}: No files processed - analysis returned empty results")
                return jsonify({"error": "No files processed - analysis returned empty results"}), 400
            
            # Rebuild all_analyses from results
            all_analyses_from_results = {}
            for r in results:
                if 'analysis' in r:
                    all_analyses_from_results[r['file']] = r['analysis']
            
            # Format as JSON for frontend
            try:
                logger.info(f"Session {session_id}: Formatting results as JSON")
                summary_json = format_consolidated_summary_json(results, all_analyses_from_results)
                logger.info(f"Session {session_id}: JSON formatted. Rows: {len(summary_json)}")
            except Exception as e:
                logger.error(f"Session {session_id}: Error formatting results: {str(e)}")
                return jsonify({
                    "error": f"Error formatting results: {str(e)}",
                    "type": type(e).__name__
                }), 500
            
            # Get current token usage stats
            stats = get_current_stats()
            
            logger.info(f"Session {session_id}: Returning success response. Files processed: {len(results)}")
            logger.info(f"Session {session_id}: Log file: {log_filename}")
            
            return jsonify({
                "status": "success",
                "results": summary_json,
                "files_processed": len(results),
                "token_stats": stats,
                "log_file": log_filename  # Return log filename for debugging
            })
    
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"Session {session_id}: Unexpected error: {str(e)}\n{error_trace}")
        return jsonify({
            "error": str(e),
            "type": type(e).__name__,
            "traceback": error_trace,
            "log_file": log_filename
        }), 500

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({
        "error": "File too large. Maximum size is 100MB.",
        "type": "RequestEntityTooLarge"
    }), 413

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy"})

@app.route('/stats', methods=['GET'])
def stats():
    """Get current token usage statistics"""
    try:
        stats = get_current_stats()
        return jsonify(stats)
    except Exception as e:
        # Return default stats if there's an error reading the file
        return jsonify({
            "total_requests": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost": 0.0,
            "model": "gpt-5.1",
            "history": [],
            "error": str(e)
        }), 200  # Still return 200 to avoid breaking frontend

@app.route('/stats/reset', methods=['POST'])
def reset_stats_endpoint():
    """Reset token usage statistics (admin only - add auth in production)"""
    reset_stats()
    return jsonify({"status": "stats reset", "stats": get_current_stats()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

