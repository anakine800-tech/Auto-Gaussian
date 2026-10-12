import {object} from './provenance';
export function HistoricalReview({data}:{data:unknown}) {
 if(!object(data)||typeof data.classification!=='string')return <span>无绑定的历史科学审核报告</span>;
 const acceptances=Array.isArray(data.acceptances)?data.acceptances:[];
 const scopes=acceptances.map(a=>object(a)&&object(a.review_evidence)?a.review_evidence:null);
 return <span className="historical-review"><strong>历史验证 · {data.classification} · {String(data.acceptance_state??'未记录验收')}</strong>
 {scopes.length?scopes.map((s,i)=><span className="review-scope" key={i}>验收范围：{s?.scope==='v30-a-first-live-plumbing-smoke-test'?'首次运行链路验证（smoke），不是研究级结果。':typeof s?.scope==='string'?s.scope:'原报告未记录，不能据此推断研究级验收。'}{Array.isArray(s?.limitations)&&s.limitations.map((v,j)=><span key={j}>{String(v)}</span>)}</span>):<span className="review-scope">验收范围：原报告未记录，不能据此推断研究级验收。</span>}
 <small>沿用已保存历史报告，未重新验证或授予验收。</small></span>;
}
