#!/usr/bin/env python3
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
import subprocess
from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import logging.handlers

app = Flask(__name__)
CORS(app)

CONFIG_PATH = Path.home() / '.config' / 'archblocker'
CONFIG_FILE = CONFIG_PATH / 'config.json'
HOSTS_FILE = '/etc/hosts'
LOG_FILE = CONFIG_PATH / 'archblocker.log'

# Set up enhanced logging
def setup_logging():
    CONFIG_PATH.mkdir(parents=True, exist_ok=True)
    
    # Create a formatter that includes more details
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s'
    )
    
    # File handler with rotation
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3
    )
    file_handler.setFormatter(formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # Set up the logger
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
            return {'websites': []}
        with open(CONFIG_FILE) as f:
            config = json.load(f)
            logger.debug(f"Loaded config with {len(config.get('websites', []))} websites")
            return config
    except Exception as e:
        logger.error(f"Failed to load config: {str(e)}")
        return {'websites': []}

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
        logger.debug(f"Current time (HHMM): {current_time}")

        if website['enabled']:
            # Convert HH:MM to HHMM integers
            start_time = int(website['startTime'].replace(':', ''))
            end_time = int(website['endTime'].replace(':', ''))
            logger.debug(f"Start time (HHMM): {start_time}, End time (HHMM): {end_time}")

            # Handle time ranges
            if start_time <= end_time:
                # Standard case: time range does not cross midnight
                logger.debug("Standard time range (does not cross midnight).")
                if start_time <= current_time <= end_time:
                    logger.info(f"🚫 {website['url']} should be BLOCKED now ({current.strftime('%H:%M')} is between {website['startTime']}-{website['endTime']})")
                    return True
            else:
                # Cross-midnight case
                logger.debug("Cross-midnight time range.")
                if current_time >= start_time or current_time <= end_time:
                    logger.info(f"🚫 {website['url']} should be BLOCKED now ({current.strftime('%H:%M')} is between {website['startTime']}-{website['endTime']})")
                    return True

            # If neither condition matches
            logger.info(f"✓ {website['url']} should be ALLOWED now ({current.strftime('%H:%M')} is outside {website['startTime']}-{website['endTime']})")
        return False
    except Exception as e:
        logger.error(f"Error checking block status for {website.get('url', 'unknown')}: {str(e)}")
        return False



def update_hosts_file(websites):
    logger.info("=== Starting hosts file update ===")
    
    if os.geteuid() != 0:
        logger.error("❌ ERROR: Must run as root! Current UID: %d", os.geteuid())
        return False

    try:
        # Remove immutable attribute
        result = subprocess.run(['chattr', '-i', HOSTS_FILE], capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Failed to remove immutable attribute: {result.stderr}")
            return False
        logger.debug("Removed immutable attribute from hosts file")

        # Read current hosts file
        with open(HOSTS_FILE, 'r') as f:
            hosts_content = f.readlines()
        logger.debug(f"Read {len(hosts_content)} lines from hosts file")

        # Remove our block section
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

        # Add new blocks
        blocks = []
        for site in websites:
            if check_block_needed(site):
                blocks.extend([
                    f'0.0.0.0 {site["url"]}\n',
                    f'0.0.0.0 www.{site["url"]}\n'
                ])
                logger.debug(f"Added block for {site['url']}")

        if blocks:
            new_content.append('\n## ARCHBLOCKER START\n')
            new_content.extend(blocks)
            new_content.append('## ARCHBLOCKER END\n')

        # Write back to hosts file
        with open(HOSTS_FILE, 'w') as f:
            f.writelines(new_content)
        logger.info(f"Updated hosts file with {len(blocks)} blocks")

        # Set immutable attribute back
        result = subprocess.run(['chattr', '+i', HOSTS_FILE], capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Failed to set immutable attribute: {result.stderr}")
            return False
        logger.debug("Set immutable attribute on hosts file")

        # Flush DNS cache
        result = subprocess.run(['systemd-resolve', '--flush-caches'], capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Failed to flush DNS cache: {result.stderr}")
            return False
        logger.debug("Flushed DNS cache")

        return True

    except Exception as e:
        logger.error(f"❌ Error updating hosts file: {str(e)}", exc_info=True)
        return False

@app.route('/websites', methods=['GET'])
def get_websites():
    try:
        config = load_config()
        logger.info(f"Returning {len(config['websites'])} websites")
        return jsonify(config['websites'])
    except Exception as e:
        logger.error(f"Error getting websites: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

@app.route('/websites', methods=['POST'])
def add_website():
    try:
        config = load_config()
        website = request.json
        logger.info(f"Adding new website: {website['url']}")
        config['websites'].append(website)
        save_config(config)
        update_hosts_file(config['websites'])
        return jsonify(website)
    except Exception as e:
        logger.error(f"Error adding website: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

@app.route('/websites/<path:url>', methods=['DELETE'])
def remove_website(url):
    try:
        logger.info(f"Removing website: {url}")
        config = load_config()
        config['websites'] = [w for w in config['websites'] if w['url'] != url]
        save_config(config)
        update_hosts_file(config['websites'])
        return '', 204
    except Exception as e:
        logger.error(f"Error removing website: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

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

    # Run the blocker in a separate thread
    from threading import Thread
    blocker_thread = Thread(target=run_blocker, daemon=True)
    blocker_thread.start()
    
    # Run the Flask app
    logger.info("Starting Flask application on port 5000")
    app.run(port=5000)

if __name__ == '__main__':
    main()