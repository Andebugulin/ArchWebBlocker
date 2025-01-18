import React, { useState, useEffect } from 'react';
import { Terminal } from 'lucide-react';

const ArchBlockerTerminal = () => {
  const [websites, setWebsites] = useState([]);
  const [currentCommand, setCurrentCommand] = useState('');
  const [history, setHistory] = useState([
    'Welcome to ArchBlocker v1.0',
    'Type "help" for available commands',
    '-----------------------------------'
  ]);
  const [showHelp, setShowHelp] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchWebsites();
  }, []);

  const fetchWebsites = async () => {
    try {
      const response = await fetch('http://localhost:5000/websites');
      if (!response.ok) throw new Error('Failed to fetch websites');
      const data = await response.json();
      setWebsites(data);
      addToHistory('Successfully loaded website configurations');
    } catch (err) {
      setError('Failed to connect to ArchBlocker service');
      addToHistory('⚠️ Error: Failed to connect to ArchBlocker service');
    }
  };

  const addToHistory = (text) => {
    setHistory(prev => [...prev, text]);
  };

  const validateTime = (time) => {
    const timeRegex = /^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$/;
    return timeRegex.test(time);
  };

  const validateUrl = (url) => {
    return url.includes('.') && !url.includes(' ') && !url.includes('http');
  };

  const processCommand = async (cmd) => {
    const parts = cmd.toLowerCase().split(' ');
    
    switch(parts[0]) {
      case 'help':
        setShowHelp(true);
        break;

      case 'add':
        if (parts.length >= 4) {
          if (!validateUrl(parts[1])) {
            addToHistory('Error: Invalid URL format. Use domain.com format');
            break;
          }
          if (!validateTime(parts[2]) || !validateTime(parts[3])) {
            addToHistory('Error: Invalid time format. Use HH:MM format');
            break;
          }

          const newSite = {
            url: parts[1],
            startTime: parts[2],
            endTime: parts[3],
            enabled: true
          };

          try {
            const response = await fetch('http://localhost:5000/websites', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
              },
              body: JSON.stringify(newSite),
            });

            if (!response.ok) throw new Error('Failed to add website');
            
            await fetchWebsites();
            addToHistory(`Added ${parts[1]} (blocked ${parts[2]}-${parts[3]})`);
          } catch (err) {
            addToHistory(`⚠️ Error: Failed to add website - ${err.message}`);
          }
        } else {
          addToHistory('Usage: add domain.com HH:MM HH:MM');
          addToHistory('Example: add facebook.com 09:00 17:00');
        }
        break;

      case 'remove':
        if (parts[1]) {
          try {
            const response = await fetch(`http://localhost:5000/websites/${parts[1]}`, {
              method: 'DELETE',
            });

            if (!response.ok) throw new Error('Failed to remove website');
            
            await fetchWebsites();
            addToHistory(`Removed ${parts[1]}`);
          } catch (err) {
            addToHistory(`⚠️ Error: Failed to remove website - ${err.message}`);
          }
        }
        break;

      case 'list':
        addToHistory('Current blocked sites:');
        websites.forEach(site => {
          addToHistory(`${site.enabled ? '✓' : '✗'} ${site.url} (${site.startTime}-${site.endTime})`);
        });
        break;

      case 'clear':
        setHistory([]);
        break;

      case 'refresh':
        addToHistory('Refreshing website list...');
        await fetchWebsites();
        break;

      case 'status':
        if (error) {
          addToHistory('⚠️ Service Status: ERROR');
          addToHistory(error);
        } else {
          addToHistory('✓ Service Status: Running');
          addToHistory(`Total websites configured: ${websites.length}`);
        }
        break;

      default:
        addToHistory(`Command not found: ${cmd}`);
        addToHistory('Type "help" for available commands');
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (currentCommand.trim()) {
      addToHistory(`> ${currentCommand}`);
      processCommand(currentCommand.trim());
      setCurrentCommand('');
    }
  };

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-gray-900 p-4">
      <div className="w-full max-w-2xl rounded-lg bg-black p-4 text-green-400 shadow-lg border border-green-500">
        <div className="flex items-center gap-2 mb-4 border-b border-green-500 pb-2">
          <Terminal size={24} />
          <h1 className="text-xl font-mono">ArchBlocker Terminal</h1>
        </div>
        
        <div className="h-96 overflow-y-auto font-mono mb-4 p-2">
          {history.map((line, i) => (
            <div key={i} className="mb-1">
              {line}
            </div>
          ))}
          
          {showHelp && (
            <div className="bg-gray-900 p-2 rounded mt-2">
              <p className="text-yellow-400">Available Commands:</p>
              <p>add &lt;website&gt; &lt;startTime&gt; &lt;endTime&gt;</p>
              <p>remove &lt;website&gt;</p>
              <p>list - Show all blocked sites</p>
              <p>refresh - Refresh website list</p>
              <p>status - Check service status</p>
              <p>clear - Clear terminal</p>
              <p>help - Show this help</p>
              <br />
              <p className="text-yellow-400">Examples:</p>
              <p>add facebook.com 09:00 17:00</p>
              <p>remove instagram.com</p>
            </div>
          )}
        </div>
        
        <form onSubmit={handleSubmit} className="flex gap-2">
          <span className="text-green-500">$</span>
          <input
            type="text"
            value={currentCommand}
            onChange={(e) => setCurrentCommand(e.target.value)}
            className="flex-1 bg-transparent border-none outline-none text-green-400 font-mono"
            placeholder="Type a command..."
          />
        </form>
      </div>
    </div>
  );
};

export default ArchBlockerTerminal;