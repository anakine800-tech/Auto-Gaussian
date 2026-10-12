import {test,expect} from '@playwright/test';
import {parseStructure,buildInput,emptyForm,routePatch,lineDiff} from '../src/draft-model';
import {parseIRC,parseGoodVibes,populations} from '../src/offline-science';
import {csv,canonical} from '../src/local-records';
const water='3\nwater\nO 0 0 0\nH 0 .7 .5\nH 0 -.7 .5\n';
const form={...emptyForm,title:'water',method:'HF',basis:'STO-3G',environment:'gas',charge:'0',multiplicity:'1',cores:'8',memory:'12',walltime:'24:00:00'};
test('structure import rejects ambiguous formats, multiple frames and non-finite coordinates',()=>{
 expect(parseStructure(water,'a.xyz').geometry.atoms).toHaveLength(3);
 for(const data of [water+water,water.replace('.7','NaN'),water.replace('H 0 .7 .5','H 0 0 .7 .5')])expect(()=>parseStructure(data,'a.xyz')).toThrow();
 const input=buildInput(form,parseStructure(water,'a.xyz').geometry);expect(parseStructure(input,'a.gjf').charge).toBe(0);expect(parseStructure(input,'a.gjf').geometry.atoms).toHaveLength(3);expect(()=>parseStructure(input+'--Link1--\n'+input,'a.gjf')).toThrow();
});
test('draft input preserves explicit choices and checks electron parity and method requirements',()=>{
 const g=parseStructure(water,'a.xyz').geometry;expect(buildInput(form,g)).toContain('# HF/STO-3G Opt Freq');
 for(const patch of [{multiplicity:'2'},{environment:''},{basis:'GenECP'},{extra:'Geom=AllCheck'},{cores:'0'},{memory:'NaN'},{method:'HF\n# opt'},{walltime:'24:99:00'}])expect(()=>buildInput({...form,...patch},g)).toThrow();
});
test('repair changes only reviewed route and preserves remainder; opt never added to SP',()=>{
 const input=buildInput(form,parseStructure(water,'a.xyz').geometry);const fixed=routePatch(input,'scf',512);expect(fixed).toContain('SCF=(XQC,MaxCycle=512)');expect(fixed.split('\n\n').slice(1)).toEqual(input.split('\n\n').slice(1));expect(routePatch(fixed,'scf',200).match(/MaxCycle=/g)).toHaveLength(1);expect(routePatch(input,'opt',300)).toContain('Opt=(MaxCycle=300)');expect(()=>routePatch(input.replace('Opt Freq','SP'),'opt',300)).toThrow();expect(lineDiff(input,fixed)).toContain('+ # HF/STO-3G');
});
test('IRC cannot connect gaps, changed atom order, non-finite energy or ordinary optimization XYZ',()=>{
 const g=parseStructure(water,'a.xyz').geometry;const data={schema:'autog-irc-trajectory/1',coordinate_units:'point-index',points:[0,1].map(i=>({branch:'forward',point:i,coordinate:i,energy_hartree:-75-i*.01,geometry:g}))};expect(parseIRC(JSON.stringify(data),'a.json').points).toHaveLength(2);
 expect(()=>parseIRC(JSON.stringify({...data,points:[data.points[0],{...data.points[1],point:3}]}),'a.json')).toThrow();
 expect(()=>parseIRC(JSON.stringify({...data,points:[data.points[0],{...data.points[1],geometry:{units:'angstrom',atoms:[...g.atoms].reverse()}}]}),'a.json')).toThrow();expect(()=>parseIRC(water+water,'a.xyz')).toThrow();
});
test('GoodVibes table retains corrected energy and rejects ambiguous tables, invalid rows and duplicates',()=>{
 const raw='Temperature 298.15 K\nStructure E G(T) qh-G(T)\n********\no conf1 -75 -74.95 -74.94\no conf2 -75 -74.94 -74.93\n********\n';const t=parseGoodVibes(raw);expect(t.rows[0].values['qh-G(T)']).toBe(-74.94);expect(()=>parseGoodVibes(raw+raw)).toThrow();expect(()=>parseGoodVibes(raw.replace('conf2','conf1'))).toThrow();expect(()=>parseGoodVibes(raw.replace('o conf2','x conf2'))).toThrow();expect(()=>parseGoodVibes(raw.replace('-74.93','NaN'))).toThrow();
});
test('Boltzmann normalization is shift invariant, stable at large differences and matches known ratio',()=>{
 const p=populations([0,Math.log(3)*8.31446261815324*298.15/2625499.6394799],298.15);expect(p[0]).toBeCloseTo(.75,10);expect(p[1]).toBeCloseTo(.25,10);expect(populations([-100,-100],300)).toEqual([.5,.5]);expect(populations([-1000,1000],1)).toEqual([1,0]);expect(()=>populations([0,1],0)).toThrow();expect(()=>populations([0],300)).toThrow();
});
test('export CSV neutralizes formula strings without turning numeric negative energies into text',()=>{expect(csv([['=cmd','-75.1','@test','-H2O']])).toContain('"\'=cmd","-75.1","\'@test","\'-H2O"');expect(canonical({z:1,a:{y:2,x:3}})).toBe('{"a":{"x":3,"y":2},"z":1}');});
