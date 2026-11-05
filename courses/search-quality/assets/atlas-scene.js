/* Rendering for the atlas. Navigation and accessible controls live in flow.js. */
(() => {
  'use strict';
  class AtlasScene {
    constructor(host, graph, onFrame) {
      this.host=host; this.graph=graph; this.onFrame=onFrame;
      this.state={x:0,y:0,zoom:1,yaw:0}; this.target={...this.state};
      this.velocity={x:0,y:0,zoom:0,yaw:0}; this.paused=false;
      this.reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
      this.selected=''; this.activePath=''; this.last=0; this.time=0;
      this.canvas=document.createElement('canvas'); this.canvas.setAttribute('aria-hidden','true');
      host.prepend(this.canvas); this.mode='3d';
      try { this.init3D(); } catch (_) {
        this.mode='2d'; this.canvas.remove(); this.canvas=document.createElement('canvas');
        this.canvas.setAttribute('aria-hidden','true'); host.prepend(this.canvas); this.ctx=this.canvas.getContext('2d');
      }
      host.dataset.renderer=this.mode;
      this.resize(); this.observer=new ResizeObserver(()=>this.resize()); this.observer.observe(host);
      this.frame=this.frame.bind(this); this.raf=requestAnimationFrame(this.frame);
      document.addEventListener('visibilitychange',()=>{if(!document.hidden){this.last=0;cancelAnimationFrame(this.raf);this.raf=requestAnimationFrame(this.frame);}});
      this.canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();host.dispatchEvent(new CustomEvent('atlas-context-lost'));});
    }
    init3D() {
      const T=window.THREE; if(!T)throw new Error('3D unavailable'); this.T=T;
      this.renderer=new T.WebGLRenderer({canvas:this.canvas,antialias:true,alpha:true,powerPreference:'high-performance'});
      this.renderer.setPixelRatio(Math.min(devicePixelRatio,1.6));
      this.renderer.setClearColor(0xf3f2eb,0);
      this.renderer.outputColorSpace=T.SRGBColorSpace;
      this.scene=new T.Scene(); this.camera=new T.PerspectiveCamera(42,1,1,14000);
      this.points=[]; this.routes=[];
      const primary=0x285b49, secondary=0x719789;
      for(const link of this.graph.links) {
        const a=this.graph.byId.get(link.from).position, b=this.graph.byId.get(link.to).position;
        const main=link.kind==='spine', route=link.kind==='route';
        const curve=this.curve(a,b,main?70:route?95:22);
        const geometry=new T.BufferGeometry().setFromPoints(curve.getPoints(main||route?64:20));
        const line=new T.Line(geometry,new T.LineBasicMaterial({color:main?primary:secondary,transparent:true,opacity:main?.76:route?.46:.25,depthWrite:false}));
        this.scene.add(line);
        if(main||route) {
          this.routes.push({line,path:link.path});
          const count=main?2:1;
          for(let j=0;j<count;j++){
            const dot=new T.Mesh(new T.SphereGeometry(main?3.5:2.5,8,6),new T.MeshBasicMaterial({color:0x3f8065,transparent:true,opacity:.8}));
            this.scene.add(dot); this.points.push({sprite:dot,curve,offset:j/count,speed:main?.035:.024});
          }
        }
      }
      const markerGeometry=new T.SphereGeometry(1,8,6);
      for(const node of this.graph.nodes) {
        const main=node.type==='spine', branch=node.type==='branch', lesson=node.type==='lesson';
        if(!main&&!branch&&!lesson)continue;
        const material=new T.MeshBasicMaterial({color:main?0x285b49:branch?0x56816f:0x82a398,transparent:true,opacity:lesson?.72:.9});
        const dot=new T.Mesh(markerGeometry,material);
        dot.position.set(node.position.x,node.position.y,node.position.z);
        dot.scale.setScalar(main?7:branch?4:2); this.scene.add(dot);
      }
      this.marker=new T.Mesh(new T.RingGeometry(10,11.4,32),new T.MeshBasicMaterial({color:primary,transparent:true,opacity:.8,side:T.DoubleSide,depthWrite:false}));
      this.marker.visible=false; this.scene.add(this.marker);
    }
    curve(a,b,lift){const T=this.T;return new T.CubicBezierCurve3(new T.Vector3(a.x,a.y,a.z),new T.Vector3(a.x+(b.x-a.x)*.28,a.y+(b.y-a.y)*.08,a.z+lift),new T.Vector3(a.x+(b.x-a.x)*.72,a.y+(b.y-a.y)*.92,b.z+lift),new T.Vector3(b.x,b.y,b.z));}
    resize(){this.width=this.host.clientWidth;this.height=this.host.clientHeight;const aspect=this.width/this.height;this.baseDistance=aspect<1.2?Math.max(2050,2850/(2*Math.tan(21*Math.PI/180)*aspect)):2050;
      if(this.mode==='3d'){this.renderer.setSize(this.width,this.height,false);this.camera.aspect=this.width/this.height;this.camera.updateProjectionMatrix();}
      else{this.canvas.width=this.width*devicePixelRatio;this.canvas.height=this.height*devicePixelRatio;this.ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);}
      this.dirty=true;}
    focus(position,zoom=2.2){this.target.x=position.x;this.target.y=position.y;this.target.zoom=Math.max(.65,Math.min(6,zoom));this.dirty=true;}
    pan(dx,dy){const scale=this.baseDistance*.00043/this.state.zoom;this.target.x-=dx*scale*1.5;this.target.y+=dy*scale*1.5;this.target.x=Math.max(-1700,Math.min(1700,this.target.x));this.target.y=Math.max(-1100,Math.min(1100,this.target.y));this.state.x=this.target.x;this.state.y=this.target.y;this.velocity.x=this.velocity.y=0;this.dirty=true;}
    zoom(amount){this.target.zoom=Math.max(.65,Math.min(6,this.target.zoom*amount));this.dirty=true;}
    orbit(amount){this.target.yaw=Math.max(-.48,Math.min(.48,this.target.yaw+amount));this.dirty=true;}
    reset(){this.target={x:0,y:0,zoom:1,yaw:0};this.selected='';this.dirty=true;}
    select(id,path){this.selected=id;this.activePath=path||'';this.dirty=true;}
    setPaused(value){this.paused=value;this.dirty=true;}
    project(p){if(this.mode==='3d'){const v=new this.T.Vector3(p.x,p.y,p.z).project(this.camera);return{x:(v.x+1)*this.width/2,y:(1-v.y)*this.height/2,visible:v.z<1&&v.z>-1};}const s=this.width/2500*this.state.zoom;return{x:this.width/2+(p.x-this.state.x)*s,y:this.height/2-(p.y-this.state.y)*s-p.z*s*.12,visible:true};}
    frame(now){if(document.hidden){this.raf=0;return;}const dt=Math.min((now-this.last)/1000||.016,.034);this.last=now;let moving=false;
      for(const k of Object.keys(this.state)){const delta=this.target[k]-this.state[k];if(this.reduced){this.state[k]=this.target[k];this.velocity[k]=0;}else{this.velocity[k]+=(delta*95-this.velocity[k]*19.5)*dt;this.state[k]+=this.velocity[k]*dt;}if(Math.abs(delta)>.0005||Math.abs(this.velocity[k])>.0005)moving=true;}
      if(!this.paused&&!this.reduced)this.time+=dt;
      if(this.mode==='3d'){
        const d=this.baseDistance/this.state.zoom;
        this.camera.position.set(this.state.x+Math.sin(this.state.yaw)*d*.48,this.state.y-d*.24,d);this.camera.lookAt(this.state.x,this.state.y,0);this.camera.updateMatrixWorld();
        for(const p of this.points)p.sprite.position.copy(p.curve.getPoint((this.time*p.speed+p.offset)%1));
        const selected=this.graph.byId.get(this.selected);this.marker.visible=!!selected;if(selected)this.marker.position.set(selected.position.x,selected.position.y,selected.position.z+4);
        if(moving||this.dirty||(!this.paused&&!this.reduced))this.renderer.render(this.scene,this.camera);
      }else if(moving||this.dirty)this.draw2D();
      this.onFrame(this,moving);this.dirty=false;this.raf=requestAnimationFrame(this.frame);
    }
    draw2D(){const c=this.ctx;c.clearRect(0,0,this.width,this.height);
      for(const link of this.graph.links){const a=this.project(this.graph.byId.get(link.from).position),b=this.project(this.graph.byId.get(link.to).position);c.strokeStyle=link.kind==='spine'?'rgba(40,91,73,.76)':'rgba(113,151,137,.34)';c.lineWidth=link.kind==='spine'?2:1;c.beginPath();c.moveTo(a.x,a.y);c.bezierCurveTo(a.x+(b.x-a.x)*.4,a.y,a.x+(b.x-a.x)*.6,b.y,b.x,b.y);c.stroke();}}
  }
  window.AtlasScene=AtlasScene;
})();
