export function ArchiveStatus({status,termination}:{status:string;termination?:string}){
 const value=status!=='parsed'?status==='unsupported'?['unsupported','格式暂不支持']:['unparsed','无法可靠解析']:termination==='normal-termination'?['normal','正常结束 · 已解析']:termination==='error-termination'?['abnormal','异常结束 · 已解析']:['incomplete','未见终止标记'];
 return <span className={'badge calc-status calc-'+value[0]}>{value[1]}</span>;
}
export function StatusLegend(){return <div className="status-legend" aria-label="计算状态图例"><span className="calc-normal">● 正常结束且已解析</span><span className="calc-abnormal">● 异常结束</span><span className="calc-unparsed">● 无法可靠解析</span><span className="calc-submission">● 提交状态不确定</span><span className="calc-incomplete">● 未完成 / 不支持</span></div>;}
