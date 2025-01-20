#!/usr/bin/env python3
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import logging.handlers
from typing import Dict, List

app = Flask(__name__)
# Enable CORS for all routes with proper configuration
CORS(app, resources={r"/*": {"origins": "*", "methods": ["GET", "POST", "DELETE"]}})

CONFIG_PATH = Path.home() / '.config' / 'archblocker'
CONFIG_FILE = CONFIG_PATH / 'config.json'
HOSTS_FILE = '/etc/hosts'
LOG_FILE = CONFIG_PATH / 'archblocker.log'

# New constants for pause functionality
MAX_DAILY_PAUSES = 2
MAX_DAILY_PAUSE_MINUTES = 15

def setup_logging():
    CONFIG_PATH.mkdir(parents=True, exist_ok=True)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s'
    )
    
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=5*1024*1024,
        backupCount=3
    )
    file_handler.setFormatter(formatter)
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    logger = logging.getLogger('archblocker')
    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logging()

def load_config():
    try:
        if not CONFIG_FILE.exists():
            logger.info(f"Config file not found at {CONFIG_FILE}, creating new config")
            return {
                'websites': [],
                'pauses': {}
            }
        with open(CONFIG_FILE) as f:
            config = json.load(f)
            if 'pauses' not in config:
                config['pauses'] = {}
            logger.debug(f"Loaded config with {len(config.get('websites', []))} websites")
            return config
    except Exception as e:
        logger.error(f"Failed to load config: {str(e)}")
        return {'websites': [], 'pauses': {}}

def save_config(config):
    try:
        CONFIG_PATH.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        logger.debug(f"Saved config with {len(config.get('websites', []))} websites")
    except Exception as e:
        logger.error(f"Failed to save config: {str(e)}")
        raise

def check_block_needed(website):
    try:
        current = datetime.now()
        current_time = int(current.strftime('%H%M'))
        
        # Check if website is currently paused
        config = load_config()
        pauses = config.get('pauses', {})
        website_pauses = pauses.get(website['url'], {})
        
        if website_pauses:
            pause_until = datetime.fromisoformat(website_pauses.get('pause_until', ''))
            if current < pause_until:
                logger.info(f"⏸️ {website['url']} is paused until {pause_until.strftime('%H:%M')}")
                return False

        if website['enabled']:
            start_time = int(website['startTime'].replace(':', ''))
            end_time = int(website['endTime'].replace(':', ''))

            if start_time <= end_time:
                if start_time <= current_time <= end_time:
                    return True
            else:
                if current_time >= start_time or current_time <= end_time:
                    return True

        return False
    except Exception as e:
        logger.error(f"Error checking block status for {website.get('url', 'unknown')}: {str(e)}")
        return False

def can_pause_website(url: str) -> bool:
    """Check if a website can be paused based on daily limits."""
    config = load_config()
    pauses = config.get('pauses', {})
    website_pauses = pauses.get(url, {})
    
    today = datetime.now().date().isoformat()
    
    pause_count = website_pauses.get('daily_count', {}).get(today, 0)
    total_minutes = website_pauses.get('daily_minutes', {}).get(today, 0)
    
    return pause_count < MAX_DAILY_PAUSES and total_minutes < MAX_DAILY_PAUSE_MINUTES

def update_hosts_file(websites):
    logger.info("=== Starting hosts file update ===")
    
    if os.geteuid() != 0:
        logger.error("❌ ERROR: Must run as root! Current UID: %d", os.geteuid())
        return False

    try:
        result = subprocess.run(['chattr', '-i', HOSTS_FILE], capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Failed to remove immutable attribute: {result.stderr}")
            return False
            
        with open(HOSTS_FILE, 'r') as f:
            hosts_content = f.readlines()
            
        new_content = []
        in_block = False
        for line in hosts_content:
            if '## ARCHBLOCKER START' in line:
                in_block = True
                continue
            if '## ARCHBLOCKER END' in line:
                in_block = False
                continue
            if not in_block:
                new_content.append(line)

        blocks = []
        for site in websites:
            if check_block_needed(site):
                blocks.extend([
                    f'0.0.0.0 {site["url"]}\n',
                    f'0.0.0.0 www.{site["url"]}\n'
                ])
                
        if blocks:
            new_content.append('\n## ARCHBLOCKER START\n')
            new_content.extend(blocks)
            new_content.append('## ARCHBLOCKER END\n')

        with open(HOSTS_FILE, 'w') as f:
            f.writelines(new_content)
            
        result = subprocess.run(['chattr', '+i', HOSTS_FILE], capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Failed to set immutable attribute: {result.stderr}")
            return False
            
        subprocess.run(['systemd-resolve', '--flush-caches'], capture_output=True, text=True)
        
        return True

    except Exception as e:
        logger.error(f"❌ Error updating hosts file: {str(e)}", exc_info=True)
        return False

@app.route('/websites', methods=['GET'])
def get_websites():
    try:
        config = load_config()
        return jsonify(config['websites'])
    except Exception as e:
        logger.error(f"Error getting websites: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/websites', methods=['POST'])
def add_website():
    try:
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 400
            
        website = request.get_json()
        if not website:
            return jsonify({"error": "Invalid JSON data"}), 400
            
        config = load_config()
        config['websites'].append(website)
        save_config(config)
        update_hosts_file(config['websites'])
        return jsonify(website)
    except Exception as e:
        logger.error(f"Error adding website: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/websites/<path:url>', methods=['DELETE'])
def remove_website(url):
    try:
        config = load_config()
        config['websites'] = [w for w in config['websites'] if w['url'] != url]
        save_config(config)
        update_hosts_file(config['websites'])
        return '', 204
    except Exception as e:
        logger.error(f"Error removing website: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/websites/<path:url>/pause', methods=['POST'])
def pause_website(url):
    try:
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 400
            
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON data"}), 400
            
        duration_minutes = int(data.get('duration', 5))
        if duration_minutes <= 0:
            return jsonify({"error": "Invalid duration"}), 400
            
        if not can_pause_website(url):
            return jsonify({
                "error": f"Daily pause limit reached. Maximum {MAX_DAILY_PAUSES} pauses or {MAX_DAILY_PAUSE_MINUTES} minutes per day."
            }), 400

        config = load_config()
        current_time = datetime.now()
        today = current_time.date().isoformat()
        
        if url not in config['pauses']:
            config['pauses'][url] = {
                'daily_count': {},
                'daily_minutes': {},
                'pause_until': None
            }
            
        website_pauses = config['pauses'][url]
        website_pauses['pause_until'] = (current_time + timedelta(minutes=duration_minutes)).isoformat()
        website_pauses['daily_count'][today] = website_pauses['daily_count'].get(today, 0) + 1
        website_pauses['daily_minutes'][today] = website_pauses['daily_minutes'].get(today, 0) + duration_minutes
        
        save_config(config)
        update_hosts_file(config['websites'])
        
        return jsonify({
            "message": f"Paused {url} for {duration_minutes} minutes",
            "pauseUntil": website_pauses['pause_until'],
            "remainingPauses": MAX_DAILY_PAUSES - website_pauses['daily_count'][today],
            "remainingMinutes": MAX_DAILY_PAUSE_MINUTES - website_pauses['daily_minutes'][today]
        })
        
    except Exception as e:
        logger.error(f"Error pausing website: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

def main():
    if os.geteuid() != 0:
        logger.error("Must run as root. Current UID: %d", os.geteuid())
        sys.exit(1)

    def run_blocker():
        while True:
            try:
                logger.info("\n=== Blocker check starting ===")
                config = load_config()
                if not config.get('websites'):
                    logger.warning("No websites configured for blocking")
                else:
                    logger.info(f"Found {len(config['websites'])} websites in config")
                    update_hosts_file(config['websites'])
                logger.info("=== Blocker check complete ===\n")
            except Exception as e:
                logger.error(f"❌ Error in blocker loop: {str(e)}", exc_info=True)
            time.sleep(60)

    from threading import Thread
    blocker_thread = Thread(target=run_blocker, daemon=True)
    blocker_thread.start()
    
    logger.info("Starting Flask application on port 5000")
    app.run(port=5000)

if __name__ == '__main__':
    main()