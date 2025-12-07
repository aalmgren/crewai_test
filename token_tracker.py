"""
Token usage and cost tracker for OpenAI API
"""
import json
import os
from datetime import datetime
from pathlib import Path

# Pricing per 1K tokens (as of 2024)
PRICING = {
    "gpt-3.5-turbo": {
        "input": 0.0005,   # $0.50 per 1M input tokens
        "output": 0.0015   # $1.50 per 1M output tokens
    },
    "gpt-4": {
        "input": 0.03,     # $30 per 1M input tokens
        "output": 0.06     # $60 per 1M output tokens
    },
    "gpt-4-turbo": {
        "input": 0.01,     # $10 per 1M input tokens
        "output": 0.03     # $30 per 1M output tokens
    }
}

STATS_FILE = "token_usage_stats.json"

def get_stats_file_path():
    """Get path to stats file - use persistent directory on Render"""
    # On Render, the /opt/render/project/src directory persists across deployments
    # Check if we're on Render by looking for RENDER environment variable
    if os.environ.get('RENDER') or os.path.exists('/opt/render'):
        # Render production - use persistent directory
        persistent_dir = Path("/opt/render/project/src")
        persistent_dir.mkdir(parents=True, exist_ok=True)
        return persistent_dir / STATS_FILE
    else:
        # Local development - use current directory
        return Path(STATS_FILE)

def load_stats():
    """Load usage statistics from file"""
    stats_file = get_stats_file_path()
    if stats_file.exists():
        try:
            with open(stats_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    
    # Return default stats
    return {
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_requests": 0,
        "total_cost": 0.0,
        "model": "gpt-3.5-turbo",
        "last_updated": None,
        "requests": []
    }

def save_stats(stats):
    """Save usage statistics to file"""
    stats_file = get_stats_file_path()
    stats["last_updated"] = datetime.now().isoformat()
    try:
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving stats: {e}")

def calculate_cost(input_tokens, output_tokens, model="gpt-3.5-turbo"):
    """Calculate cost based on token usage"""
    if model not in PRICING:
        model = "gpt-3.5-turbo"  # Default
    
    pricing = PRICING[model]
    input_cost = (input_tokens / 1000) * pricing["input"]
    output_cost = (output_tokens / 1000) * pricing["output"]
    return input_cost + output_cost

def add_usage(input_tokens, output_tokens, model="gpt-3.5-turbo", request_info=None):
    """Add token usage to statistics"""
    stats = load_stats()
    
    # Update totals
    stats["total_input_tokens"] += input_tokens
    stats["total_output_tokens"] += output_tokens
    stats["total_requests"] += 1
    stats["model"] = model
    
    # Calculate cost for this request
    request_cost = calculate_cost(input_tokens, output_tokens, model)
    stats["total_cost"] += request_cost
    
    # Add request details
    if request_info is None:
        request_info = {}
    
    request_entry = {
        "timestamp": datetime.now().isoformat(),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cost": request_cost,
        "model": model,
        **request_info
    }
    
    stats["requests"].append(request_entry)
    
    # Keep only last 100 requests to avoid file getting too large
    if len(stats["requests"]) > 100:
        stats["requests"] = stats["requests"][-100:]
    
    save_stats(stats)
    return stats

def get_current_stats():
    """Get current usage statistics"""
    stats = load_stats()
    return {
        "total_input_tokens": stats["total_input_tokens"],
        "total_output_tokens": stats["total_output_tokens"],
        "total_tokens": stats["total_input_tokens"] + stats["total_output_tokens"],
        "total_requests": stats["total_requests"],
        "total_cost": round(stats["total_cost"], 6),
        "model": stats.get("model", "gpt-3.5-turbo"),
        "last_updated": stats.get("last_updated"),
        "cost_per_request": round(stats["total_cost"] / stats["total_requests"], 6) if stats["total_requests"] > 0 else 0
    }

def reset_stats():
    """Reset all statistics"""
    stats_file = get_stats_file_path()
    if stats_file.exists():
        stats_file.unlink()
    return get_current_stats()

