import {useEffect,useState} from 'react';
import {requestJSON} from './contract';
import './monitor.css';

type Metrics={cpu_percent:number|null;logical_cpus:number|null;load_1m:number|null;load_5m:number|null;load_15m:number|null;memory_total_mib:number|null;memory_available_mib:number|null;memory_used_mib:number|null;swap_total_mib:number|null;swap_used_mib:number|null};
type Sample={sampled_at:string;server_time:string|null;hostname:string;user:string;metrics:Metrics;processes:{pid:number;ppid:number;cpu_percent:number;rss_mib:number;elapsed:string;command:string}[];process_count:number;issues:string[];raw_sha256:string;sources:Record<string,{exit_code:number;text:string}>};
type Point={at:string;metrics:Metrics|null;error:string|null};
type Monitor={schema:string;enabled:boolean;state?:string;error?:string|null;interval_seconds?:number;age_seconds?:number|null;sample?:Sample|null;history?:Point[];route?:string;retention_samples?:number};
const stateLabels:Record<string,string>={fresh:'采样正常',partial:'部分指标不可用',waiting:'等待首次采样',stale:'最近样本已过期 / 采集异常',unavailable:'采样不可用'};
const errorLabels:Record<string,string>={'ssh-failed':'SSH 连接失败','timeout':'采样超时','host-key-verification-failed':'主机密钥校验失败','authentication-failed':'SSH 认证失败','identity-mismatch':'返回的主机或用户不匹配','output-limit':'采样输出超过上限','invalid-sample':'采样结构无效','collector-failed':'采集失败','telemetry-store-unavailable':'本地监控记录不可用'};
const num=(v:number|null|undefined,d=1)=>v==null?'—':v.toFixed(d);
const gib=(v:number|null|undefined)=>v==null?'—':(v/1024).toFixed(1);
const stamp=(s:string)=>new Date(s).toLocaleString('zh-CN',{hour12:false});
function memoryPercent(m:Metrics){return m.memory_total_mib&&m.memory_used_mib!==null?100*m.memory_used_mib/m.memory_total_mib:null;}
function Trend({history,kind,current,stale}:{history:Point[];kind:'cpu'|'memory';current:Metrics;stale:boolean}){
  const times=history.map(p=>Date.parse(p.at)),first=times[0]??0,last=times.at(-1)??first;
  const segments:string[]=[];let segment:string[]=[];
  history.forEach((p,i)=>{const v=p.metrics?(kind==='cpu'?p.metrics.cpu_percent:memoryPercent(p.metrics)):null;
    if(i&&times[i]-times[i-1]>120000){if(segment.length)segments.push(segment.join(' '));segment=[];}
    if(v===null||!Number.isFinite(v)||v<0||v>100){if(segment.length)segments.push(segment.join(' '));segment=[];}
    else segment.push(`${12+((times[i]-first)/Math.max(1,last-first))*514},${112-v}`);
  });if(segment.length)segments.push(segment.join(' '));
  const percent=kind==='cpu'?current.cpu_percent:memoryPercent(current);
  return <div className={'monitor-trend monitor-trend-'+kind}><div className="monitor-trend-heading"><strong>{kind==='cpu'?'CPU 使用率':'内存使用率'}</strong><div className="monitor-trend-value"><b>{num(percent)}%</b><span>{kind==='cpu'?`${num(current.logical_cpus,0)} 个逻辑核`:`${gib(current.memory_used_mib)} / ${gib(current.memory_total_mib)} GiB`}</span><small>{stale?'最近成功样本 · 已过期':'最近成功样本'}</small></div></div>
   <svg viewBox="0 0 600 135" role="img" aria-label={kind==='cpu'?'CPU 使用率趋势':'内存使用率趋势'}><title>{kind==='cpu'?'CPU':'内存'}使用率，右侧纵坐标 0 至 100%</title>{[0,25,50,75,100].map(v=><g key={v}><path d={`M12 ${112-v}H536`} className="monitor-grid"/><text className="monitor-axis" x="545" y={116-v}>{v}%</text></g>)}<path d="M536 12V112" className="monitor-grid"/>{segments.map((s,i)=><polyline key={i} points={s} className="monitor-line"/>)}{segments.filter(s=>!s.includes(' ')).map((s,i)=>{const [x,y]=s.split(',');return <circle key={i} cx={x} cy={y} r="2.5" className="monitor-point"/>;})}<text x="12" y="132">{history.length?new Date(history[0].at).toLocaleTimeString('zh-CN',{hour12:false}):'无采样'}</text><text x="528" y="132" textAnchor="end">{history.length?new Date(history.at(-1)!.at).toLocaleTimeString('zh-CN',{hour12:false}):''}</text></svg>
   <small>{kind==='cpu'?'整机占用率 · 1 秒采样窗口':'已用 / 总量 · 1 GiB = 1024 MiB'} · 中断处留空</small></div>;
}
export function MonitorPanel({token}:{token:string}){
  const [data,setData]=useState<Monitor|null>(null),[failed,setFailed]=useState(false);
  useEffect(()=>{const c=new AbortController();let timer:ReturnType<typeof setTimeout>|undefined;
    async function poll(){try{const value=await requestJSON('/api/monitor',token,c.signal) as unknown as Monitor;
      if(value.schema!=='autog-server-monitor/1'||typeof value.enabled!=='boolean')throw Error('contract');
      if(!c.signal.aborted){setData(value);setFailed(false);}
    }catch{if(!c.signal.aborted)setFailed(true);}finally{if(!c.signal.aborted)timer=setTimeout(poll,5000);}}
    void poll();return()=>{c.abort();clearTimeout(timer);};
  },[token]);
  const s=data?.sample,m=s?.metrics;
  return <section className="monitor-page"><div className="page-heading"><div className="eyebrow">SERVER / READ-ONLY TELEMETRY</div><h1>服务器监控 <span className={`monitor-status monitor-${failed?'stale':data?.state??'waiting'}`} role="status">{failed?'页面连接中断':data?.enabled?stateLabels[data.state??'waiting']:'未启用采样'}</span></h1></div>
    {failed&&<p className="notice warning" role="alert">无法刷新本地监控数据；下方保留的旧样本不代表当前状态。</p>}
    {!data&&!failed&&<p>正在读取监控记录…</p>}
    {data&&!data.enabled&&<p className="notice">尚未配置服务器采样。启动服务时通过本地 monitor 配置启用；页面不能指定主机或执行命令。</p>}
    {data?.enabled&&<><div className="monitor-meta"><span>{data.route}</span><span>采样主机 <b>{s?.hostname??'待核对'}</b> · 用户 {s?.user??'—'}</span><span>每 {data.interval_seconds} 秒采样 · 服务运行期间持续记录</span></div>
      {data.error&&<p className="notice warning" role="alert">{errorLabels[data.error]??'采样不可用'}。不据此判定作业失败。</p>}
      {s&&m&&<><p className="monitor-stamp">最近成功样本 · {stamp(s.sampled_at)} · {num(data.age_seconds,0)} 秒前 <span>服务器时钟 {s.server_time??'不可用'}</span></p>
        <div className="monitor-kpis"><div><small>CPU 总使用率</small><strong>{num(m.cpu_percent)}<em>%</em></strong><span>{num(m.logical_cpus,0)} 个逻辑核 · 1 秒窗口</span></div><div><small>内存使用 / 总量</small><strong>{gib(m.memory_used_mib)} <em>/ {gib(m.memory_total_mib)} GiB</em></strong><span>使用率 {num(memoryPercent(m))}% · 可用 {gib(m.memory_available_mib)} GiB</span></div><div><small>系统负载 · 1 / 5 / 15 分钟</small><strong>{num(m.load_1m)} <em>/ {num(m.load_5m)} / {num(m.load_15m)}</em></strong><span>负载不是 CPU 百分比</span></div><div><small>Swap 已用 / 总量</small><strong>{gib(m.swap_used_mib)} <em>/ {gib(m.swap_total_mib)} GiB</em></strong><span>取自 /proc/meminfo</span></div></div>
        <div className="monitor-trends"><Trend history={data.history??[]} kind="cpu" current={m} stale={failed||!['fresh','partial'].includes(data.state??'')}/><Trend history={data.history??[]} kind="memory" current={m} stale={failed||!['fresh','partial'].includes(data.state??'')}/></div>
        <div className="monitor-tables"><section className="panel"><h2>PBS 作业 · {s.user}</h2><small>原始队列状态 · qstat -u · 不自动绑定历史 Attempt</small>{s.sources.queue.exit_code===0?<pre className="monitor-queue">{s.sources.queue.text||'本次 qstat 成功返回空队列；不推断历史作业结局。'}</pre>:<p className="notice warning">队列读取不可用，不能解释为空队列。</p>}<details><summary>节点分配 · pbsnodes</summary><pre>{s.sources.nodes.exit_code===0?s.sources.nodes.text:'节点状态不可用'}</pre></details></section>
        <section className="panel"><h2>活跃进程 · {s.hostname}</h2><small>仅 {s.user} 的进程，最多显示 40 条；%CPU 为进程生命周期平均值，100% ≈ 1 核。</small>{s.issues.includes('processes')?<p className="notice warning">进程读取不可用</p>:<div className="monitor-process-scroll"><table><thead><tr><th>PID / PPID</th><th>程序</th><th>%CPU</th><th>RSS / GiB</th><th>已运行</th></tr></thead><tbody>{s.processes.map(p=><tr key={p.pid}><td>{p.pid}<small> / {p.ppid}</small></td><td><code>{p.command}</code></td><td>{num(p.cpu_percent)}</td><td>{gib(p.rss_mib)}</td><td>{p.elapsed}</td></tr>)}</tbody></table></div>}</section></div>
        <details className="panel monitor-evidence"><summary>采样来源与边界 · {s.issues.length?`${s.issues.length} 项不可用`:'来源可追溯'}</summary><p>主机资源仅属于 {s.hostname}；PBS 节点分配另行展示，不把登录节点指标当作其他计算节点指标。进程存在或队列 R 状态不代表收敛、正常结束或科学验收。</p><p>历史保留最近 {data.retention_samples} 次采样，本页显示最近 120 次。Mac 休眠、网络中断或服务关闭时不会补造数据。</p><code>采样 SHA-256 · {s.raw_sha256}</code>{s.issues.length>0&&<p>不可用字段：{s.issues.join(', ')}</p>}<details><summary>原始读取结果</summary><pre>{JSON.stringify(s.sources,null,2)}</pre></details></details>
      </>}
      {!s&&<p className="notice">尚未获得通过主机身份核对的真实样本。</p>}
    </>}
  </section>;
}
