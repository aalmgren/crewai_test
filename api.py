"""
Flask API for processing drilling data files
"""
import os
import json
import tempfile
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from crewai_test import run_analysis_api, format_consolidated_summary_json
from token_tracker import get_current_stats, reset_stats

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
    try:
        if 'files' not in request.files:
            return jsonify({"error": "No files provided"}), 400
        
        files = request.files.getlist('files')
        if not files or files[0].filename == '':
            return jsonify({"error": "No files selected"}), 400
        
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
                    except Exception as e:
                        return jsonify({
                            "error": f"Error saving file {file.filename}: {str(e)}",
                            "type": type(e).__name__
                        }), 400
            
            if not saved_files:
                return jsonify({"error": "No CSV files were saved"}), 400
            
            # Run analysis
            try:
                results = run_analysis_api(temp_dir)
            except Exception as e:
                return jsonify({
                    "error": f"Error during analysis: {str(e)}",
                    "type": type(e).__name__,
                    "traceback": str(e.__traceback__) if hasattr(e, '__traceback__') else None
                }), 500
            
            if not results:
                return jsonify({"error": "No files processed - analysis returned empty results"}), 400
            
            # Rebuild all_analyses from results
            all_analyses_from_results = {}
            for r in results:
                if 'analysis' in r:
                    all_analyses_from_results[r['file']] = r['analysis']
            
            # Format as JSON for frontend
            try:
                summary_json = format_consolidated_summary_json(results, all_analyses_from_results)
            except Exception as e:
                return jsonify({
                    "error": f"Error formatting results: {str(e)}",
                    "type": type(e).__name__
                }), 500
            
            # Get current token usage stats
            stats = get_current_stats()
            
            return jsonify({
                "status": "success",
                "results": summary_json,
                "files_processed": len(results),
                "token_stats": stats
            })
    
    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "type": type(e).__name__,
            "traceback": traceback.format_exc()
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
            "model": "gpt-3.5-turbo",
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

