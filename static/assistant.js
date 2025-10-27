(function(){
  // Basic Voice Assistant: recognition + synthesis + command router
  const state = {
    recognizing: false,
    recognition: null,
    custom: JSON.parse(localStorage.getItem('sinsay:customCmds')||'[]'),
    prefs: JSON.parse(localStorage.getItem('sinsay:prefs')||'{}'),
  };

  // Non-overlapping assistant TTS: queue speech until all page audios are idle
  let speakChain = Promise.resolve();
  function isAnyAudioPlaying(){
    try{
      const audios = Array.from(document.querySelectorAll('audio'));
      return audios.some(a => a && !a.paused && !a.ended && a.currentTime > 0);
    }catch(_){ return false; }
  }
  function waitForAudioIdle(timeoutMs=120000){
    return new Promise(resolve =>{
      if (!isAnyAudioPlaying()) return resolve();
      const audios = Array.from(document.querySelectorAll('audio'));
      let done=false; const tryResolve = ()=>{ if (!done && !isAnyAudioPlaying()){ done=true; cleanup(); resolve(); } };
      const onStop = ()=> tryResolve();
      const cleanup = ()=>{ audios.forEach(a=>{ try{ a.removeEventListener('pause', onStop); a.removeEventListener('ended', onStop); }catch(_){} }); if (tid) clearTimeout(tid); if (intId) clearInterval(intId); };
      audios.forEach(a=>{ try{ a.addEventListener('pause', onStop, { once:false }); a.addEventListener('ended', onStop, { once:false }); }catch(_){} });
      const intId = setInterval(tryResolve, 500);
      const tid = setTimeout(()=>{ if (!done){ done=true; cleanup(); resolve(); } }, timeoutMs);
    });
  }
  function speak(text, lang='es-ES'){
    speakChain = speakChain.then(async ()=>{
      await waitForAudioIdle();
      // also wait if TTS currently speaking
      await new Promise(r=>{ if (!speechSynthesis.speaking) return r(); const chk=setInterval(()=>{ if (!speechSynthesis.speaking){ clearInterval(chk); r(); } }, 100); });
      try{
        const u = new SpeechSynthesisUtterance(text);
        u.lang = lang;
        return new Promise(res=>{ u.onend=()=>res(); u.onerror=()=>res(); speechSynthesis.speak(u); });
      }catch(e){ console.warn('speechSynthesis error', e); }
    });
  }

  function saveCustom(){ localStorage.setItem('sinsay:customCmds', JSON.stringify(state.custom)); }

  function addCustomCommand(phrase, action){
    state.custom.push({phrase: phrase.toLowerCase(), action});
    saveCustom();
  }

  // Command handlers
  const actions = {
    navigate: (path)=>{ window.location.href = path; },
    search: (q)=>{ try{ const inp = document.getElementById('searchInput'); if(inp){ inp.value=q; inp.dispatchEvent(new Event('input')); } else { window.location.href='/biblioteca'; setTimeout(()=>{ const i=document.getElementById('searchInput'); if(i){ i.value=q; i.dispatchEvent(new Event('input')); }}, 500); } }catch(e){}},
    mood: (m)=>{ if (typeof window.applyMood === 'function'){ window.applyMood(m); } else { window.location.href='/descubrir'; setTimeout(()=>{ if (typeof window.applyMood==='function') window.applyMood(m); }, 500);} },
    play: ()=>{ try{ const btn = document.getElementById('btnPlay'); if(btn){ btn.click(); } }catch(e){} },
    openReproductor: ()=>{ window.location.href='/reproductor'; },
  };

  function routeCommand(text){
    const t = (text||'').toLowerCase();
    // Custom exact matches first
    for (const c of state.custom){ if (t.includes(c.phrase)){ try{ eval(c.action); }catch(e){} return 'custom'; } }

    // Built-ins
    if (/(reproduce|pon|play).*(relajante|relajación|tranquilo|calma)/.test(t)){
      actions.navigate('/descubrir');
      setTimeout(()=> actions.mood('relax'), 600);
      return 'mood:relax';
    }
    if (/(reproduce|pon|play).*(energ[íi]a|energizante|activ[o|a])/.test(t)){
      actions.navigate('/descubrir');
      setTimeout(()=> actions.mood('energy'), 600);
      return 'mood:energy';
    }
    const m = t.match(/(busca|buscar|encuentra) (.+)/);
    if (m && m[2]){ actions.search(m[2].trim()); return 'search'; }
    if (/reproductor|player|escuchar ahora/.test(t)){ actions.openReproductor(); return 'openReproductor'; }
    if (/pausa|reanuda|play|reproduce/.test(t)){ actions.play(); return 'playToggle'; }

    return 'none';
  }

  function ensureButton(){
    if (document.getElementById('sinsay-voice-btn')) return;
    const btn = document.createElement('button');
    btn.id='sinsay-voice-btn';
    btn.title='Asistente de voz';
    btn.style.position='fixed';
    btn.style.right='20px';
    btn.style.bottom='20px';
    btn.style.width='56px';
    btn.style.height='56px';
    btn.style.borderRadius='9999px';
    btn.style.border='1px solid rgba(255,255,255,0.25)';
    btn.style.background='linear-gradient(135deg, rgba(124,58,237,0.9), rgba(236,72,153,0.9))';
    btn.style.color='#fff';
    btn.style.zIndex='999';
    btn.style.boxShadow='0 8px 24px rgba(0,0,0,0.35)';
    btn.textContent='🎤';
    btn.addEventListener('click', toggleRecognition);
    document.body.appendChild(btn);
  }

  function ensureRecognition(){
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR){ console.warn('SpeechRecognition no soportado'); return null; }
    if (!state.recognition){
      const r = new SR();
      r.lang='es-ES'; r.continuous=false; r.interimResults=false;
      r.onresult = (e)=>{
        try{
          const text = e.results[0][0].transcript;
          const cmd = routeCommand(text);
          if (cmd!=='none') speak('Hecho'); else speak('No entendí, intenta de nuevo');
        }catch(err){ console.warn(err); }
      };
      r.onend = ()=>{ state.recognizing=false; refreshBtn(); };
      state.recognition = r;
    }
    return state.recognition;
  }

  function refreshBtn(){
    const btn = document.getElementById('sinsay-voice-btn');
    if (!btn) return; btn.style.opacity = state.recognizing ? '0.8':'1';
    btn.textContent = state.recognizing? '🛑' : '🎤';
  }

  function toggleRecognition(){
    const r = ensureRecognition();
    if (!r){ speak('Tu navegador no soporta reconocimiento de voz.'); return; }
    if (!state.recognizing){ try{ r.start(); state.recognizing=true; refreshBtn(); speak('Te escucho'); }catch(e){} }
    else { try{ r.stop(); state.recognizing=false; refreshBtn(); speak('Listo'); }catch(e){} }
  }

  // Expose minimal API for custom commands UI later
  window.SinsayAssistant = { addCustomCommand, speak };

  // Init
  window.addEventListener('DOMContentLoaded', ensureButton);
})();
