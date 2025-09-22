function toggleTheme(){
  const body=document.body;
  const dark=body.classList.toggle('theme-dark');
  if(dark){ localStorage.setItem('theme','dark'); }
  else{ localStorage.setItem('theme','light'); }
}
(function(){
  const saved=localStorage.getItem('theme');
  if(saved==='dark'){ document.body.classList.add('theme-dark'); }
})();

function toggleMenu(){
  var list=document.getElementById('navList');
  if(!list) return;
  list.classList.toggle('open');
}

function copyToClipboard(text){
  if(!navigator.clipboard) return;
  navigator.clipboard.writeText(text).catch(()=>{});
}

async function playText(text, lang){
  const audio=new Audio(`/api/tts?text=${encodeURIComponent(text)}&lang=${encodeURIComponent(lang||'en')}`);
  await audio.play();
}

