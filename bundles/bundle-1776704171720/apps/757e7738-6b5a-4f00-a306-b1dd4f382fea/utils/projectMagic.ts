const lines = (s = '') => s.replace(/\r/g, '').split(/\n+/).map(x => x.trim()).filter(Boolean);
const stripLead = (s: string) => s.replace(/^[-*\d\s.]+/, '').trim();
const keyify = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
const unique = (rows: string[]) => {
  const seen = new Set<string>();
  return rows.filter(x => {
    const key = keyify(x);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
};
export function draftProjectPlan(name = '', objective = '', notes = '') {
  const text = [objective, notes].join('\n');
  const raw = [...lines(text), ...text.split(/[.!?]+/)].map(stripLead).filter(x => x.length > 12);
  const actionish = /(review|research|call|email|draft|confirm|gather|collect|create|update|compare|schedule|book|follow up|send|finalize|decide|get|ask|prepare|submit|pay|file|organize)/i;
  const keep = raw.filter(x => actionish.test(x) || x.includes(':') || x.split(' ').length <= 10);
  const seeded = [
    `Clarify the outcome and constraints for ${name || 'this project'}`,
    objective ? 'Break the objective into 3-5 concrete milestones' : '',
    /quote|estimate|bid|vendor|contractor|pressure|wash|repair|clean/i.test(text) ? 'Get quotes, confirm scope, timing, and price' : '',
    /doctor|therapy|clinic|medical|insurance/i.test(text) ? 'Confirm provider, time, paperwork, and follow-up requirements' : '',
    'List blockers, decisions, and deadlines',
    'Stage the next 2-4 actions as tasks'
  ].filter(Boolean) as string[];
  return unique([...keep, ...seeded]).map(x => x.replace(/^[A-Z][a-z]+:\s*/, '').trim()).filter(x => x.length > 9).slice(0, 8).map(x => x[0].toUpperCase() + x.slice(1));
}
