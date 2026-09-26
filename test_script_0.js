
        document.getElementById('generate-btn').addEventListener('click', async () => {
            const prompt = document.getElementById('prompt-input').value;
            if (!prompt.trim()) return;
            
            // Clear old terminal outputs from previous executions
            document.querySelectorAll('.terminal-output-box').forEach(el => el.remove());

            document.getElementById('btn-text').innerText = 'Agents Thinking...';
            document.getElementById('btn-spinner').classList.remove('hidden');
            document.getElementById('error-banner').classList.add('hidden');
            document.getElementById('results-section').classList.add('hidden');

            try {
                // Get OS context dynamically
                const osContext = navigator.userAgent;

                const res = await fetch('http://localhost:8000/api/generate-workflow', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        natural_language_prompt: prompt,
                        user_agent_os: osContext
                    })
                });
                
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'API Error');

                // Render Discussion
                const discussionHtml = data.multi_agent_discussion.map(agent => `
                    <div class="bg-slate-900 p-4 rounded-lg border border-slate-700">
                        <span class="text-indigo-400 font-bold text-sm uppercase">${agent.agent_name}</span>
                        <p class="text-slate-300 text-sm mt-1">${agent.thought}</p>
                    </div>
                `).join('');
                document.getElementById('discussion-container').innerHTML = discussionHtml;

                // Security Status
                const statusDiv = document.getElementById('guardrail-status');
                if (data.is_safe) {
                    statusDiv.className = 'p-4 rounded-xl border bg-emerald-900/30 border-emerald-500/50 text-emerald-300';
                    statusDiv.innerHTML = `✅ Target OS Detected: ${data.target_os} (Safe)`;
                } else {
                    statusDiv.className = 'p-4 rounded-xl border bg-red-900/30 border-red-500/50 text-red-300';
                    statusDiv.innerHTML = `🛑 BLOCKED: Malicious Intent Detected`;
                }

                // Script Output
                if (data.requires_browser && data.target_url) {
                    document.getElementById('powershell-output').innerText = "// Web Execution intent intercepted\nLaunch Browser: " + data.target_url;
                } else {
                    document.getElementById('powershell-output').innerText = data.shell_script || "// Blocked by Security Agent";
                }
                document.getElementById('results-section').classList.remove('hidden');

                // Trigger Native Host Execution Agent with STRICT Human-in-the-Loop
                if (data.is_safe) {
                    const statusSpan = document.createElement('span');
                    statusSpan.className = "animate-pulse ml-4 text-yellow-300";
                    statusSpan.innerText = "⚡ Awaiting Human Confirmation...";
                    statusDiv.appendChild(statusSpan);
                    
                    try {
                        if (data.requires_browser && data.target_url) {
                            // URL routing - fetch browsers from host
                            const bRes = await fetch('http://localhost:8003/browsers');
                            const bData = await bRes.json();
                            const browsers = bData.browsers || ["Default Browser"];
                            
                            // Pop SweetAlert2 Selection ALWAYS
                            const inputOptions = {};
                            browsers.forEach(b => inputOptions[b] = b);
                            
                            const { value: selectedBrowser, isConfirmed } = await Swal.fire({
                                title: 'Human Confirmation Required',
                                text: `Do you approve opening this URL: ${data.target_url}? Please select a browser to proceed.`,
                                input: 'select',
                                inputOptions: inputOptions,
                                inputPlaceholder: 'Select your preferred browser...',
                                showCancelButton: true,
                                confirmButtonText: 'Yes, Execute!',
                                cancelButtonText: 'No, Cancel',
                                background: '#1e293b',
                                color: '#fff',
                                confirmButtonColor: '#10b981',
                                cancelButtonColor: '#ef4444',
                            });
                            
                            if (isConfirmed && selectedBrowser) {
                                statusSpan.innerText = `🚀 Launching ${selectedBrowser}...`;
                                
                                const osIsLinux = data.target_os.toLowerCase().includes('linux') || data.target_os.toLowerCase().includes('ubuntu');
                                let script = "";
                                
                                if (osIsLinux) {
                                    let cmd = "xdg-open";
                                    if (selectedBrowser.toLowerCase().includes('chrome')) cmd = "google-chrome";
                                    if (selectedBrowser.toLowerCase().includes('brave')) cmd = "brave-browser";
                                    if (selectedBrowser.toLowerCase().includes('firefox')) cmd = "firefox";
                                    script = `${cmd} "${data.target_url}" &`;
                                } else {
                                    script = `Start-Process "${selectedBrowser}" -ArgumentList "${data.target_url}"`;
                                    if (selectedBrowser.toLowerCase().includes('chrome')) script = `Start-Process "chrome" -ArgumentList "${data.target_url}"`;
                                    if (selectedBrowser.toLowerCase().includes('brave')) script = `Start-Process "brave" -ArgumentList "${data.target_url}"`;
                                    if (selectedBrowser.toLowerCase().includes('firefox')) script = `Start-Process "firefox" -ArgumentList "${data.target_url}"`;
                                }
                                
                                const execRes = await fetch('http://localhost:8003/execute', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ script: script })
                                });
                                const execData = await execRes.json();
                                
                                statusSpan.className = "ml-4 text-emerald-400 font-bold"; if (data.expected_process) { const validationBadge = document.createElement('span'); if (execData.validated) { validationBadge.className = "ml-4 px-2 py-1 bg-green-900/50 text-green-400 text-xs rounded border border-green-700 font-bold"; validationBadge.innerText = "✅ Validation Success (100%): " + data.expected_process + " is running"; } else { validationBadge.className = "ml-4 px-2 py-1 bg-red-900/50 text-red-400 text-xs rounded border border-red-700 font-bold"; validationBadge.innerText = "❌ Validation Failed: " + data.expected_process + " did not open"; } statusSpan.after(validationBadge); }
                                statusSpan.innerText = `🚀 Executed via ${selectedBrowser}!`;
                                
                                // Inject Terminal Output Box for Browser Execution
                                if (execData.output) {
                                    const outputDiv = document.createElement('div');
                                    outputDiv.className = "terminal-output-box mt-4 p-4 bg-black text-green-400 font-mono text-sm rounded border border-green-900 overflow-auto whitespace-pre-wrap w-full max-h-64 shadow-inner";
                                    outputDiv.innerText = `> ${script}\n\n${execData.output.trim()}`;
                                    statusDiv.parentElement.appendChild(outputDiv);
                                }
                            } else {
                                statusSpan.className = "ml-4 text-red-400 font-bold";
                                statusSpan.innerText = "🛑 Execution Cancelled by Human";
                            }
                        } else if (data.shell_script) {
                            // Standard execution (e.g., vscode) - require Yes/No
                            const { isConfirmed } = await Swal.fire({
                                title: 'Human Confirmation Required',
                                html: `Do you approve the execution of this system script?<br><br><pre class="text-left text-xs bg-slate-900 p-2 rounded text-emerald-400">${data.shell_script.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</pre>`,
                                icon: 'warning',
                                showCancelButton: true,
                                confirmButtonText: 'Yes, Execute!',
                                cancelButtonText: 'No, Cancel',
                                background: '#1e293b',
                                color: '#fff',
                                confirmButtonColor: '#10b981',
                                cancelButtonColor: '#ef4444',
                            });

                            if (isConfirmed) {
                                statusSpan.innerText = "🚀 Dispatching to Host...";
                                const execRes = await fetch('http://localhost:8003/execute', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ script: data.shell_script, expected_process: data.expected_process })
                                });
                                const execData = await execRes.json();
                                
                                statusSpan.className = "ml-4 text-emerald-400 font-bold"; if (data.expected_process) { const validationBadge = document.createElement('span'); if (execData.validated) { validationBadge.className = "ml-4 px-2 py-1 bg-green-900/50 text-green-400 text-xs rounded border border-green-700 font-bold"; validationBadge.innerText = "✅ Validation Success (100%): " + data.expected_process + " is running"; } else { validationBadge.className = "ml-4 px-2 py-1 bg-red-900/50 text-red-400 text-xs rounded border border-red-700 font-bold"; validationBadge.innerText = "❌ Validation Failed: " + data.expected_process + " did not open"; } statusSpan.after(validationBadge); }
                                statusSpan.innerText = "🚀 Executed on Host Machine!";
                                
                                // Inject Terminal Output Box
                                if (execData.output) {
                                    const outputDiv = document.createElement('div');
                                    outputDiv.className = "terminal-output-box mt-4 p-4 bg-black text-green-400 font-mono text-sm rounded border border-green-900 overflow-auto whitespace-pre-wrap w-full max-h-64 shadow-inner";
                                    outputDiv.innerText = `> ${data.shell_script}\n\n${execData.output.trim()}`;
                                    
                                    // Append it right below the status bar
                                    statusDiv.parentElement.appendChild(outputDiv);
                                }
                            } else {
                                statusSpan.className = "ml-4 text-red-400 font-bold";
                                statusSpan.innerText = "🛑 Execution Cancelled by Human";
                            }
                        }
                    } catch (e) {
                        console.warn("Host Executor offline", e);
                        statusSpan.className = "ml-4 text-red-400 text-xs";
                        statusSpan.innerText = "(Host Executor Offline - Check Console)";
                    }
                }

                // Render Mermaid (Dynamically fixing the missing "graph TD;" issue)
                if (data.mermaid_diagram_body) {
                    const container = document.getElementById('mermaid-container');
                    try {
                        const fullMermaidString = `graph TD;\n${data.mermaid_diagram_body.replace(/graph TD;?/g, '')}`; // Ensure no duplicate headers
                        const { svg } = await window.mermaid.render('mermaid-chart', fullMermaidString);
                        container.innerHTML = svg;
                    } catch(err) {
                        console.error('Mermaid render failed', err);
                        container.innerHTML = `<div class="text-red-500 text-sm">Mermaid Syntax Error</div>`;
                    }
                }

            } catch (err) {
                const banner = document.getElementById('error-banner');
                banner.innerText = err.message || 'Network error';
                banner.classList.remove('hidden');
            } finally {
                document.getElementById('btn-text').innerText = 'Execute';
                document.getElementById('btn-spinner').classList.add('hidden');
            }
        });
    