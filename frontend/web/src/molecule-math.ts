// Display connectivity only, never a molecular identity or bond-order assignment.
// Radius values (Å): 3Dmol.js bondLength.ts; see docs/gaussview-display-handoff.md.
export type Atom={center:number;atomic_number:number;x:number;y:number;z:number};
export type Bond={a:number;b:number;distance:number};
export const RADII:Readonly<Record<number,number>>=Object.freeze({1:.37,3:1.34,4:.90,5:.82,6:.77,7:.75,8:.73,9:.71,11:1.54,12:1.30,13:1.18,14:1.11,15:1.06,16:1.02,17:.99,19:1.96,20:1.74,21:1.44,22:1.56,23:1.25,25:1.39,26:1.25,27:1.26,28:1.21,29:1.38,30:1.31,35:1.14,46:1.31,47:1.53,53:1.33,78:1.28,79:1.44});
export function inferDisplayBonds(atoms:readonly Atom[]) {
  const bonds:Bond[]=[];const unsupported=[...new Set(atoms.filter(a=>!RADII[a.atomic_number]).map(a=>a.atomic_number))];
  let closePairs=0;
  for(let i=0;i<atoms.length;i++)for(let j=i+1;j<atoms.length;j++){
    const a=atoms[i],b=atoms[j],ra=RADII[a.atomic_number],rb=RADII[b.atomic_number];if(!ra||!rb)continue;
    const d=Math.hypot(a.x-b.x,a.y-b.y,a.z-b.z);if(d*d<.5){closePairs++;continue;}
    if(d<=ra+rb+.25){bonds.push({a:a.center,b:b.center,distance:d});if(bonds.length>3000)return {bonds:[],unsupported,closePairs,overflow:true};}
  }
  return {bonds,unsupported,closePairs,overflow:false};
}
type Vec=[number,number,number];
const sub=(a:Atom,b:Atom):Vec=>[a.x-b.x,a.y-b.y,a.z-b.z];
const dot=(a:Vec,b:Vec)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
const cross=(a:Vec,b:Vec):Vec=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const norm=(a:Vec)=>Math.hypot(...a);
export function measure(atoms:readonly Atom[],mode:'distance'|'angle'|'torsion'):number|null {
  const n=mode==='distance'?2:mode==='angle'?3:4;if(atoms.length!==n)return null;
  if(mode==='distance')return norm(sub(atoms[0],atoms[1]));
  if(mode==='angle'){
    const u=sub(atoms[0],atoms[1]),v=sub(atoms[2],atoms[1]),den=norm(u)*norm(v);if(den<1e-12)return null;
    return Math.acos(Math.max(-1,Math.min(1,dot(u,v)/den)))*180/Math.PI;
  }
  const b0=sub(atoms[0],atoms[1]),b1=sub(atoms[2],atoms[1]),b2=sub(atoms[3],atoms[2]);const length=norm(b1);if(length<1e-12)return null;
  const axis=b1.map(v=>v/length) as Vec;
  const v=b0.map((x,i)=>x-dot(b0,axis)*axis[i]) as Vec,w=b2.map((x,i)=>x-dot(b2,axis)*axis[i]) as Vec;
  if(norm(v)*norm(w)<1e-12)return null;
  return Math.atan2(dot(cross(axis,v),w),dot(v,w))*180/Math.PI;
}
export function rotate(x:number,y:number,z:number,angles:readonly number[]){
  const [rx,ry]=angles;const xx=x*Math.cos(ry)+z*Math.sin(ry),zz=-x*Math.sin(ry)+z*Math.cos(ry);
  return {x:xx,y:y*Math.cos(rx)-zz*Math.sin(rx),z:y*Math.sin(rx)+zz*Math.cos(rx)};
}
// Orthonormal, right-handed principal axes for the initial camera only.
// The original coordinates and all measurements remain unchanged.
export function cameraBasis(atoms:readonly Atom[]):number[][] {
  const center=[0,1,2].map(i=>atoms.reduce((s,a)=>s+[a.x,a.y,a.z][i]/atoms.length,0));
  let a=Array.from({length:3},()=>[0,0,0]);let v=[[1,0,0],[0,1,0],[0,0,1]];
  for(const atom of atoms){const d=[atom.x-center[0],atom.y-center[1],atom.z-center[2]];for(let i=0;i<3;i++)for(let j=0;j<3;j++)a[i][j]+=d[i]*d[j];}
  const multiply=(x:number[][],y:number[][])=>x.map(row=>[0,1,2].map(j=>row.reduce((sum,value,k)=>sum+value*y[k][j],0)));
  const transpose=(x:number[][])=>[0,1,2].map(i=>x.map(row=>row[i]));
  for(let step=0;step<40;step++){
    const [p,q]=[[0,1],[0,2],[1,2]].sort((x,y)=>Math.abs(a[y[0]][y[1]])-Math.abs(a[x[0]][x[1]]))[0];
    if(Math.abs(a[p][q])<1e-12)break;
    const angle=.5*Math.atan2(2*a[p][q],a[q][q]-a[p][p]),c=Math.cos(angle),s=Math.sin(angle),r=[[1,0,0],[0,1,0],[0,0,1]];
    r[p][p]=c;r[q][q]=c;r[p][q]=s;r[q][p]=-s;a=multiply(multiply(transpose(r),a),r);v=multiply(v,r);
  }
  const axes=[0,1,2].sort((i,j)=>a[j][j]-a[i][i]).map(i=>v.map(row=>row[i]) as Vec);
  for(const axis of axes){const index=[0,1,2].sort((i,j)=>Math.abs(axis[j])-Math.abs(axis[i]))[0];if(axis[index]<0)for(let k=0;k<3;k++)axis[k]*=-1;}
  return [axes[0],axes[1],cross(axes[0],axes[1])];
}
