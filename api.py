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

app = Flask(__name__)
# Enable CORS for GitHub Pages and all origins
CORS(app, resources={
    r"/*": {
        "origins": ["https://aalmgren.github.io", "http://localhost:*", "http://192.168.*"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

@app.route('/')
def index():
    return jsonify({"status": "API is running"})

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
            for file in files:
                if file.filename.endswith('.csv'):
                    file_path = os.path.join(temp_dir, file.filename)
                    file.save(file_path)
            
            # Run analysis
            results = run_analysis_api(temp_dir)
            
            if not results:
                return jsonify({"error": "No files processed"}), 400
            
            # Rebuild all_analyses from results
            all_analyses_from_results = {}
            for r in results:
                if 'analysis' in r:
                    all_analyses_from_results[r['file']] = r['analysis']
            
            # Format as JSON for frontend
            summary_json = format_consolidated_summary_json(results, all_analyses_from_results)
            
            # Get current token usage stats
            stats = get_current_stats()
            
            return jsonify({
                "status": "success",
                "results": summary_json,
                "files_processed": len(results),
                "token_stats": stats
            })
    
    except Exception as e:
        return jsonify({
            "error": str(e),
            "type": type(e).__name__
        }), 500

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

