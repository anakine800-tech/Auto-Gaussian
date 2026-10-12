import {stages} from './workflow-stages';
import type {StageID,StageTask} from './workflow-stages';
export type LayoutEvidence={record_id:string;source:string;sha256:string;recorded_at:string|null};
export type LayoutNode={node_id:string;project_id:string;workflow_run_id:string;stage:StageID;label:string;task_ids:string[];branch_id:string|null;evidence:LayoutEvidence[]};
export type LayoutEdge={from:string;to:string;evidence:LayoutEvidence[]};
export type WorkflowLayout={schema:'autog-workflow-layout/1';availability:'available'|'unavailable';reason:string|null;nodes:LayoutNode[];edges:LayoutEdge[]};
export type LayoutRead={layout:WorkflowLayout|null;invalid:boolean};
const text=(v:unknown):v is string=>typeof v==='string'&&v.trim().length>0&&v.length<=1024;
function evidence(v:unknown):v is LayoutEvidence[]{return Array.isArray(v)&&v.length>0&&v.length<=100&&v.every(e=>e&&text(e.record_id)&&text(e.source)&&typeof e.sha256==='string'&&/^[a-f0-9]{64}$/.test(e.sha256)&&(e.recorded_at===null||text(e.recorded_at)&&/^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$/.test(e.recorded_at)&&Number.isFinite(Date.parse(e.recorded_at))));}
// Invalid future graph data cannot take down the existing task table, nor become
// a trusted dependency diagram. No HTML, filesystem paths, commands or URLs execute.
export function readLayout(raw:unknown,tasks:StageTask[]):LayoutRead{
 if(raw===undefined)return {layout:null,invalid:false};
 try{
  const v=raw as WorkflowLayout;
  if(!v||v.schema!=='autog-workflow-layout/1'||!['available','unavailable'].includes(v.availability)||!Array.isArray(v.nodes)||!Array.isArray(v.edges)||v.nodes.length>2000||v.edges.length>4000)throw Error();
  if(v.availability==='unavailable'){if(v.nodes.length||v.edges.length||!text(v.reason))throw Error();return {layout:v,invalid:false};}
  if(v.reason!==null||!v.nodes.length)throw Error();
  const ids=new Map<string,LayoutNode>();
  const taskKeys=new Map<string,number>();for(const t of tasks){const key=JSON.stringify([t.project_id,t.workflow_run_id,t.task_id]);taskKeys.set(key,(taskKeys.get(key)??0)+1);}
  let references=0;
  for(const n of v.nodes){
   if(!n||!text(n.node_id)||ids.has(n.node_id)||!text(n.label)||!text(n.project_id)||!text(n.workflow_run_id)||!stages.some(s=>s.id===n.stage)||!(n.branch_id===null||text(n.branch_id))||!evidence(n.evidence)||!Array.isArray(n.task_ids)||!n.task_ids.length||new Set(n.task_ids).size!==n.task_ids.length)throw Error();
   references+=n.task_ids.length;if(references>4000)throw Error();
   for(const id of n.task_ids)if(!text(id)||taskKeys.get(JSON.stringify([n.project_id,n.workflow_run_id,id]))!==1)throw Error();
   ids.set(n.node_id,n);
  }
  const edges=new Set<string>(),indegree=new Map(v.nodes.map(n=>[n.node_id,0])),next=new Map(v.nodes.map(n=>[n.node_id,[] as string[]]));
  for(const e of v.edges){if(!e||!evidence(e.evidence))throw Error();const a=ids.get(e.from),b=ids.get(e.to),key=JSON.stringify([e.from,e.to]);if(!a||!b||a===b||a.project_id!==b.project_id||a.workflow_run_id!==b.workflow_run_id||edges.has(key))throw Error();edges.add(key);next.get(e.from)!.push(e.to);indegree.set(e.to,indegree.get(e.to)!+1);}
  const ready=[...indegree].filter(([,n])=>n===0).map(([id])=>id);let visited=0;
  while(ready.length){const id=ready.pop()!;visited++;for(const to of next.get(id)!){indegree.set(to,indegree.get(to)!-1);if(indegree.get(to)===0)ready.push(to);}}
  if(visited!==ids.size)throw Error();
  return {layout:v,invalid:false};
 }catch{return {layout:null,invalid:true};}
}
