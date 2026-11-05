/* Navigation and accessible content for the spatial learning atlas. */
(() => {
  'use strict';
  const data=window.LEARNING_FLOW;if(!data||!window.AtlasScene)return;
  const $=s=>document.querySelector(s), $$=s=>Array.from(document.querySelectorAll(s));
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const green='#4b9474', storageKey='search-quality-course-v1';
  let read=new Set();try{const stored=JSON.parse(localStorage.getItem(storageKey)||'[]');if(Array.isArray(stored))read=new Set(stored.filter(v=>typeof v==='string'));}catch(_){}
  const graph={nodes:[],routes:[],links:[],byId:new Map()}, lessons=[], positions=[[-760,330],[0,360],[760,330],[-760,-330],[0,-360],[760,-330]];
  const add=n=>{graph.nodes.push(n);graph.byId.set(n.id,n);return n;};
  const link=(from,to,kind,path='')=>graph.links.push({from,to,kind,path,color:green});
  data.paths.forEach((path,pi)=>{
    const [x,y]=positions[pi],z=pi%2*15;
    graph.routes.push({id:path.id,position:{x,y,z},color:green,order:pi});
    const root=add({id:path.id,type:'path',path:path.id,label:path.label,description:path.description,color:green,position:{x,y:y+150,z},branches:[]});
    path.branches.forEach((branch,bi)=>{
      const count=path.branches.length,columns=count>3?3:count,row=Math.floor(bi/columns);
      const bx=x+(bi%columns-(columns-1)/2)*(count>3?175:210),by=y+(count>3?(row===0?38:-120):-15);
      const bn=add({id:path.id+'/'+branch.id,type:'branch',path:path.id,branch:branch.id,label:branch.label,description:branch.description,reason:branch.sequence_reason,color:green,position:{x:bx,y:by,z:z+18},lessons:[],starts:branch.start_bvids});
      root.branches.push(bn);link(root.id,bn.id,'branch',path.id);
      const extra=(data.external||[]).filter(e=>e.path===path.id&&e.branch===branch.id).map(e=>({...e,bvid:e.id,external:true,ready:false,href:e.url,summary:e.summary||'',role:'基础课程'}));
      const entries=[...branch.lessons,...extra];
      entries.forEach((lesson,li)=>{
        const angle=li*2.399963, radius=25+Math.sqrt(li)*14;
        const n=add({id:path.id+'/'+branch.id+'/'+lesson.bvid,type:'lesson',path:path.id,branch:branch.id,label:lesson.title,description:lesson.summary,color:green,lesson,position:{x:bx+Math.cos(angle)*radius,y:by-48+Math.sin(angle)*radius*.62,z:z+20+li%5*2},featured:bi===0&&li===0});
        lessons.push(n);bn.lessons.push(n);link(bn.id,n.id,'leaf',path.id);
      });
    });
  });
  data.spine.forEach((s,i)=>{
    const original=lessons.find(n=>n.lesson.bvid===s.bvid);
    add({id:'spine/'+s.id,type:'spine',label:s.label,description:s.description,path:original?.path||'ai',branch:original?.branch,lesson:original?.lesson,position:{x:(i-1)*460,y:15,z:65},color:green,order:i});
    if(i)link('spine/'+data.spine[i-1].id,'spine/'+s.id,'spine');
  });
  graph.routes.forEach((r,i)=>{if(data.spine.length)link('spine/'+data.spine[i%data.spine.length].id,r.id,'route',r.id);});
  const world=$('#world-labels'),inspector=$('#inspector'),library=$('#library-panel'),search=$('#atlas-search'),results=$('#search-results'),tooltip=$('#node-tooltip');
  let selected='',free=false,journey=[null,...data.spine.map(s=>'spine/'+s.id),...data.paths.map(p=>p.id)],step=0,journeyName='三个共同起点，再选择一条路线',paused=false,scene;
  const nodes=new Map();
  const cover=(l,cls='',lazy=true)=>l.cover?`<img class="${cls}" src="${esc(l.cover)}" alt="" ${lazy?'loading="lazy"':''}>`:'';
  const status=l=>l.external?'外部课程':l.ready?(read.has(l.bvid)?'已读':'图文笔记'):'视频待整理';
  for(const n of graph.nodes){
    const b=document.createElement('button');b.className='world-node '+n.type;b.dataset.node=n.id;b.style.setProperty('--node',green);b.setAttribute('aria-label',n.label);b.setAttribute('aria-pressed','false');
    let title=esc(n.label);
    if(n.type==='path')title+=`<small>${n.branches.reduce((s,b)=>s+b.lessons.length,0)} 条内容 · ${n.branches.length} 个分支</small>`;
    if(n.type==='spine')title=`<b>0${n.order+1}</b><span class="spine-full">${title}</span><span class="spine-short">${['认识 AI','定义问题','检验结果'][n.order]}</span>`;
    b.innerHTML=`<i class="node-dot"></i><span class="node-title">${title}</span>`;
    if(n.type==='lesson'){
      b.classList.toggle('pending',!n.lesson.ready&&!n.lesson.external);b.classList.toggle('external',!!n.lesson.external);
      b.innerHTML+=`<span class="video-preview">${cover(n.lesson)||'<span class="preview-placeholder">'+esc(n.lesson.external?'基础课程':'视频')+'</span>'}<strong>${esc(n.label)}</strong><small>${esc(status(n.lesson))}</small></span>`;
    }
    b.addEventListener('click',()=>selectNode(n.id));
    b.addEventListener('mouseenter',()=>{tooltip.textContent=n.label;tooltip.hidden=false;});
    b.addEventListener('mousemove',e=>{tooltip.style.left=Math.max(8,Math.min(innerWidth-310,e.clientX+15))+'px';tooltip.style.top=Math.min(innerHeight-80,e.clientY+18)+'px';});
    b.addEventListener('mouseleave',()=>tooltip.hidden=true);
    world.append(b);nodes.set(n.id,b);
  }
  $('#route-nav').innerHTML=data.paths.map(p=>`<button class="route-option" data-route="${p.id}" aria-pressed="false" style="--route:${green}"><i></i><span>${esc(p.label)}</span><small>${lessons.filter(n=>n.path===p.id).length}</small></button>`).join('');
  $('#total-badge').textContent=`${lessons.length} 条内容 / 6 条路线`;
  $('#all-count').textContent=lessons.length;
  const safeImages=root=>root.querySelectorAll('img').forEach(img=>img.addEventListener('error',()=>{img.hidden=true;},{once:true}));safeImages(world);
  function refreshProgress(){
    $('#read-count').textContent=`已读 ${lessons.filter(n=>n.lesson.ready&&read.has(n.lesson.bvid)).length} / ${lessons.filter(n=>n.lesson.ready).length} 篇`;
    for(const n of graph.nodes){const b=nodes.get(n.id);b.classList.toggle('is-read',!!n.lesson&&read.has(n.lesson.bvid));const label=b.querySelector('.video-preview small');if(label)label.textContent=status(n.lesson);}
    $$('[data-done]').forEach(input=>input.checked=read.has(input.dataset.done));
    const active=graph.byId.get(selected);if(active?.lesson&&inspector.querySelector('.detail-meta span'))inspector.querySelector('.detail-meta span').textContent=status(active.lesson);
  }
  function setRead(bv,value){value?read.add(bv):read.delete(bv);try{localStorage.setItem(storageKey,JSON.stringify([...read]));}catch(_){}refreshProgress();}
  window.addEventListener('storage',e=>{if(e.key!==storageKey)return;try{const items=JSON.parse(e.newValue||'[]');read=new Set(Array.isArray(items)?items:[]);}catch(_){read=new Set();}refreshProgress();});
  const projectionOrder=[...graph.nodes].sort((a,b)=>(a.type==='lesson')-(b.type==='lesson'));
  let previousProjection='';
  function project(s){
    const projectionKey=[s.state.x.toFixed(2),s.state.y.toFixed(2),s.state.zoom.toFixed(4),s.state.yaw.toFixed(4),s.width,s.height,selected,inspector.hidden].join('|');
    if(projectionKey===previousProjection)return;previousProjection=projectionKey;
    const zoom=s.state.zoom,small=innerWidth<650,collision=[];
    if(!selected)collision.push({x:220,y:95,w:390,h:135});
    // Prominent labels reserve space before optional covers. Every content node remains present.
    for(const n of projectionOrder){
      const b=nodes.get(n.id),p=s.project(n.position),visible=p.visible&&p.x>-160&&p.x<innerWidth+160&&p.y>-150&&p.y<innerHeight+150;
      b.hidden=!visible;if(!visible)continue;
      b.style.transform=`translate(${p.x.toFixed(1)}px,${p.y.toFixed(1)}px)`;
      b.style.zIndex=n.id===selected?'5':n.type==='lesson'?'2':'3';
      const title=b.querySelector('.node-title');
      if(n.type!=='lesson'){
        title.hidden=n.type==='branch'&&(zoom<1.6||small);
        if(!title.hidden){const w=n.type==='path'?180:n.type==='spine'?190:155;collision.push(n.type==='branch'?{x:p.x+10,y:p.y-10,w,h:20}:{x:p.x-w/2,y:p.y-18,w,h:50});}
        continue;
      }
      title.hidden=true;
      let show=n.id===selected||(!small&&((zoom<1.5&&n.featured)||(zoom>=1.5&&n.path===graph.byId.get(selected)?.path&&(n.featured||zoom>3.2))));
      const width=small?96:innerWidth>=1900?138:122,height=small?104:132;
      const candidates=[{x:p.x-width/2,y:p.y-height-16},{x:p.x+22,y:p.y-35},{x:p.x-width-22,y:p.y-35},{x:p.x-width/2,y:p.y+20}].map(pos=>({...pos,w:width,h:height}));
      let box=candidates[0];
      if(show&&n.id!==selected){
        box=candidates.find(box=>box.x>215&&box.x+box.w<innerWidth-(inspector.hidden?40:365)&&box.y>110&&box.y+box.h<innerHeight-125&&!collision.some(r=>box.x<r.x+r.w+8&&box.x+box.w+8>r.x&&box.y<r.y+r.h+8&&box.y+box.h+8>r.y));
        show=!!box;
      }
      b.classList.toggle('featured',show);
      if(show){b.style.zIndex=n.id===selected?'5':'4';const preview=b.querySelector('.video-preview');preview.style.left=(box.x-p.x)+'px';preview.style.top=(box.y-p.y)+'px';preview.style.bottom='auto';preview.style.transform='none';collision.push(box);}
    }
  }
  scene=new window.AtlasScene($('#atlas-stage'),graph,project);
  $('#renderer-status').textContent=scene.mode==='3d'?'空间视图 · 可拖动':'平面兼容视图 · 可拖动';
  function renderJourney(){
    $('#journey-name').textContent=journeyName;$('#journey-count').textContent=`${step+1} / ${journey.length}`;
    $('#journey-stops').innerHTML=journey.map((id,i)=>`<button data-step="${i}" class="${i<step?'visited':''}" ${i===step?'aria-current="step"':''} aria-label="${esc(id?graph.byId.get(id)?.label:'全部内容全景')}" title="${esc(id?graph.byId.get(id)?.label:'全景')}"></button>`).join('');
    $('[data-action=prev]').disabled=step===0;$('[data-action=next]').disabled=step===journey.length-1;
  }
  function setFree(value){free=value;const b=$('[data-action=mode]');b.setAttribute('aria-pressed',String(free));b.innerHTML=free?'自由探索 <span>↗</span>':'循线阅读 <span>⌁</span>';$('#gesture-hint').textContent=free?'滚轮缩放 · 拖动平移 · 点击返回路线':'滚轮沿线 · 拖动探索 · Ctrl + 滚轮缩放';}
  function focusNode(n){
    if(!n){scene.reset();return;}
    let zoom=n.type==='path'?1.85:n.type==='branch'?3:n.type==='spine'?2.05:4;
    if(innerWidth<650)zoom*=.85*scene.baseDistance/3400;
    // Leave a little room beside the inspector without moving the target off screen.
    const anchorY=n.position.y-(n.type==='path'?210:n.type==='branch'?50:0);
    scene.focus({x:n.position.x+(innerWidth>900?115:0),y:anchorY+(innerWidth<650?90:0)},zoom);
  }
  function listButtons(items){return `<div class="detail-list">${items.map((n,i)=>`<button data-select="${esc(n.id)}"><span>${String(i+1).padStart(2,'0')}</span>${esc(n.label)}</button>`).join('')}</div>`;}
  function renderInspector(n){
    if(!n){inspector.hidden=true;return;}
    const path=data.paths.find(p=>p.id===n.path),branch=graph.byId.get(n.path+'/'+n.branch);
    let body=`<header><span>${esc(n.type==='spine'?'共同起点':path?.label||'学习路线')}</span><button class="close-button" data-action="close-detail" aria-label="收起详情">×</button></header>`;
    if(n.lesson){
      const l=n.lesson;body+=cover(l,'detail-cover',false)+`<h2>${esc(n.label)}</h2><p class="description">${esc(n.description||'打开视频，了解这一话题。')}</p><div class="detail-meta"><span>${esc(status(l))}</span>${l.author?`<span>${esc(l.author)}</span>`:''}${l.duration_seconds?`<span>${Math.round(l.duration_seconds/60)} 分钟</span>`:''}</div>`;
      const href=l.external?l.href:l.ready?l.href:'https://www.bilibili.com/video/'+l.bvid+'/';
      body+=`<a class="primary-link" href="${esc(href)}" ${l.external||!l.ready?'target="_blank" rel="noopener noreferrer"':''}>${l.external?'前往观看课程':l.ready?'打开图文笔记':'前往 B 站观看'}<span>↗</span></a>`;
      if(l.ready&&!l.external)body+=`<label class="progress-control"><input type="checkbox" data-done="${esc(l.bvid)}" ${read.has(l.bvid)?'checked':''}> 我已读过这篇</label>`;
      if(l.external)body+=`<p class="detail-quiet">外部视频 · 暂无本站笔记${l.year?' · '+esc(l.year)+' 年内容':''}</p>${l.prerequisites?`<p class="description">阅读起点：${esc(l.prerequisites)}</p>`:''}`;
      if(branch)body+=`<div class="detail-context"><div class="context-item">${esc(path.label)}</div><div class="context-item">${esc(branch.label)}</div><p>${esc(branch.reason)}</p><button class="rail-utility" data-select="${esc(branch.id)}">查看这个分支 →</button></div>`;
    }else{
      body+=`<h2>${esc(n.label)}</h2><p class="description">${esc(n.description)}</p>`;
      if(n.type==='path')body+=`<p class="detail-quiet">选择一个问题深入，或沿下方路线继续。</p>`+listButtons(n.branches);
      else body+=`<p class="description">${esc(n.reason)}</p>`+listButtons(n.lessons);
    }
    inspector.innerHTML=body;inspector.hidden=false;inspector.scrollTop=0;safeImages(inspector);
  }
  function setSelection(id,focus=true,history=true){
    const n=graph.byId.get(id);selected=n?id:'';scene.select(selected,n?.path);nodes.forEach((b,key)=>{b.classList.toggle('selected',key===selected);b.setAttribute('aria-pressed',String(key===selected));});
    $$('#route-nav [data-route]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.route===n?.path)));
    $('#atlas-caption').classList.toggle('dimmed',!!n);renderInspector(n);if(focus)focusNode(n);
    if(history){const hash=n?'#'+n.id:'';if(location.hash!==hash)window.history.pushState(null,'',location.pathname+location.search+hash);}
    $('#atlas-status').textContent=n?'已定位：'+n.label:'全部内容全景';
  }
  function selectNode(id,history=true){
    const n=graph.byId.get(id);if(!n)return;
    library.hidden=true;results.hidden=true;tooltip.hidden=true;setFree(false);
    if(n.type==='path'){
      journey=[n.id,...n.branches.flatMap(b=>[b.id,...b.starts.map(bv=>b.lessons.find(l=>l.lesson.bvid===bv)?.id).filter(Boolean)])];journeyName=n.label+' · 从主干到具体问题';step=0;
    }else if(n.type==='branch'){
      const ordered=[...n.lessons].sort((a,b)=>n.starts.includes(b.lesson.bvid)-n.starts.includes(a.lesson.bvid));journey=[n.id,...ordered.map(l=>l.id)];journeyName=n.label;step=0;
    }else{const found=journey.indexOf(id);if(found>=0)step=found;else{const b=graph.byId.get(n.path+'/'+n.branch);journey=b?[b.id,...b.lessons.map(l=>l.id)]:[id];step=journey.indexOf(id);journeyName=b?.label||'共同起点';}}
    setSelection(id,true,history);renderJourney();
  }
  function goStep(index){step=Math.max(0,Math.min(journey.length-1,index));setFree(false);setSelection(journey[step]);renderJourney();}
  function overview(){tooltip.hidden=true;journey=[null,...data.spine.map(s=>'spine/'+s.id),...data.paths.map(p=>p.id)];step=0;journeyName='三个共同起点，再选择一条路线';setFree(false);setSelection('');renderJourney();}
  function showLibrary(){
    library.innerHTML=`<header class="panel-heading"><div><h2>全部内容</h2><p>${lessons.filter(n=>n.lesson.ready).length} 篇图文笔记 · ${lessons.filter(n=>!n.lesson.ready&&!n.lesson.external).length} 条待整理视频 · ${lessons.filter(n=>n.lesson.external).length} 条外部课程</p></div><button class="close-button" data-action="close-list" aria-label="收起全部内容">×</button></header>`+data.paths.map(p=>`<section class="library-group" style="--route:${green}"><h3>${esc(p.label)}</h3><div class="library-grid">${lessons.filter(n=>n.path===p.id).map(n=>`<button class="library-item" data-select="${esc(n.id)}">${cover(n.lesson)}<span><strong>${esc(n.label)}</strong><small>${esc(status(n.lesson))} · ${esc(graph.byId.get(n.path+'/'+n.branch).label)}</small></span></button>`).join('')}</div></section>`).join('');library.hidden=false;safeImages(library);library.querySelector('.close-button').focus();
  }
  search.addEventListener('input',()=>{
    const q=search.value.trim().toLowerCase();if(!q){results.hidden=true;return;}
    const found=graph.nodes.filter(n=>[n.label,n.description,n.lesson?.bvid,n.lesson?.author].join(' ').toLowerCase().includes(q));
    results.innerHTML=found.length?found.slice(0,40).map(n=>`<button class="search-result" data-select="${esc(n.id)}">${esc(n.label)}<small>${esc(data.paths.find(p=>p.id===n.path)?.label||'共同起点')}${n.lesson?' · '+status(n.lesson):''}</small></button>`).join(''):'<p class="result-empty">没有找到相关内容，试试标题里的关键词。</p>';results.hidden=false;
  });
  search.addEventListener('keydown',e=>{if(e.key==='Enter'){const b=results.querySelector('[data-select]');if(b){selectNode(b.dataset.select);search.blur();}}if(e.key==='ArrowDown'){e.preventDefault();results.querySelector('button')?.focus();}if(e.key==='Escape'){results.hidden=true;search.blur();}});
  document.addEventListener('click',async e=>{
    const route=e.target.closest('[data-route]');if(route){selectNode(route.dataset.route);return;}
    const select=e.target.closest('[data-select]');if(select){selectNode(select.dataset.select);return;}
    const stop=e.target.closest('[data-step]');if(stop){goStep(Number(stop.dataset.step));return;}
    const action=e.target.closest('[data-action]')?.dataset.action;
    if(action==='next')goStep(step+1);if(action==='prev')goStep(step-1);
    if(action==='overview')overview();if(action==='zoom-in'){setFree(true);scene.zoom(1.28);}if(action==='zoom-out'){setFree(true);scene.zoom(1/1.28);}
    if(action==='orbit'){setFree(true);scene.orbit(scene.target.yaw>.2?-.48:.24);}
    if(action==='mode'){if(free){setFree(false);focusNode(graph.byId.get(journey[step]));}else setFree(true);}
    if(action==='motion'){paused=!paused;scene.setPaused(paused);const b=$('[data-action=motion]');b.setAttribute('aria-pressed',String(paused));b.setAttribute('aria-label',paused?'恢复流动':'暂停流动');b.textContent=paused?'▷':'Ⅱ';}
    if(action==='list')showLibrary();if(action==='close-list'){library.hidden=true;$('[data-action=list]').focus();}
    if(action==='close-detail')inspector.hidden=true;
    if(action==='fullscreen'){try{if(document.fullscreenElement)await document.exitFullscreen();else await $('#atlas-app').requestFullscreen();}catch(_){$('#atlas-status').textContent='当前浏览器不支持全屏，可按 F11。';}}
    if(!e.target.closest('.search-shell'))results.hidden=true;
  });
  document.addEventListener('change',e=>{if(e.target.matches('[data-done]'))setRead(e.target.dataset.done,e.target.checked);});
  document.addEventListener('keydown',e=>{
    if(e.target.matches('input,textarea,select'))return;
    if(e.key==='/'){e.preventDefault();search.focus();}
    if(e.key==='Escape'){inspector.hidden=true;library.hidden=true;results.hidden=true;}
    if(e.key==='Home'){e.preventDefault();overview();}
    if(e.key==='ArrowRight'){e.preventDefault();goStep(step+1);}if(e.key==='ArrowLeft'){e.preventDefault();goStep(step-1);}
    if(e.key==='+'||e.key==='='){setFree(true);scene.zoom(1.2);}if(e.key==='-'){setFree(true);scene.zoom(1/1.2);}
  });
  const stage=$('#atlas-stage');let wheelSum=0,wheelTime=0,wheelLock=0,drag=null,dragged=false;
  stage.addEventListener('wheel',e=>{
    e.preventDefault();const now=performance.now();
    if(e.ctrlKey||free){setFree(true);scene.zoom(Math.exp(-e.deltaY*.0016));return;}
    if(now<wheelLock)return;if(now-wheelTime>250)wheelSum=0;wheelTime=now;wheelSum+=e.deltaY*(e.deltaMode===1?16:1);
    if(Math.abs(wheelSum)>65){goStep(step+Math.sign(wheelSum));wheelSum=0;wheelLock=now+650;}
  },{passive:false});
  stage.addEventListener('pointerdown',e=>{if(e.button!==0)return;drag={x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY,id:e.pointerId};dragged=false;});
  stage.addEventListener('pointermove',e=>{
    if(!drag||e.pointerId!==drag.id)return;
    if(!dragged&&Math.hypot(e.clientX-drag.startX,e.clientY-drag.startY)>5){dragged=true;stage.setPointerCapture(e.pointerId);stage.classList.add('dragging');setFree(true);tooltip.hidden=true;}
    if(dragged){e.shiftKey?scene.orbit((e.clientX-drag.x)*.002):scene.pan(e.clientX-drag.x,e.clientY-drag.y);}
    drag.x=e.clientX;drag.y=e.clientY;
  });
  const finishDrag=()=>{drag=null;stage.classList.remove('dragging');};stage.addEventListener('pointerup',finishDrag);stage.addEventListener('pointercancel',finishDrag);
  stage.addEventListener('click',e=>{if(dragged){e.preventDefault();e.stopPropagation();dragged=false;}},{capture:true});
  stage.addEventListener('atlas-context-lost',()=>{$('#renderer-status').textContent='空间渲染已暂停';showLibrary();$('#atlas-status').textContent='已打开完整内容列表，可继续阅读。';});
  matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change',e=>{scene.reduced=e.matches;scene.dirty=true;});
  const readHash=()=>{let id;try{id=decodeURIComponent(location.hash.slice(1));}catch(_){id='';}if(graph.byId.has(id))selectNode(id,false);else{journey=[null,...data.spine.map(s=>'spine/'+s.id),...data.paths.map(p=>p.id)];step=0;journeyName='三个共同起点，再选择一条路线';setFree(false);setSelection('',true,false);renderJourney();}};
  window.addEventListener('popstate',readHash);refreshProgress();renderJourney();readHash();
  // A small inspection surface makes camera and content behavior testable without pixel guessing.
  window.atlas={graph,scene,selectNode,overview,get selected(){return selected;},get free(){return free;},get step(){return step;},get journey(){return [...journey];}};
})();
