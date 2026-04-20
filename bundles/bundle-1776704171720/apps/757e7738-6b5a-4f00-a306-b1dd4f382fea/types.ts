export interface Task {
  id:number; title:string; description:string; due_date:string|null; priority:number;
  status:string; source:string; gmail_message_id:string|null; source_details:string|null;
  tags:string|null; created_at:string;
}
export interface CalendarItem {
  id:number; title:string; event_date:string|null; starts_at:string|null; location:string|null;
  html_link:string|null; source_details:string|null; created_at?:string; updated_at?:string;
}
export interface Project {
  id:number; name:string; status:string; objective:string; plan_json:string|null; notes:string|null;
  planning_status?:string|null; planning_requested_at?:string|null; planning_summary?:string|null;
}
export interface MessageCandidate {
  id:number; message_guid:string; chat_identifier:string|null; contact:string|null; message_text:string;
  message_date:string|null; score:number; status:string; source_details:string|null;
}
export interface RecurringTemplate {
  id:number; title:string; description:string|null; priority:number; frequency:string; interval_n:number;
  start_date:string; next_due_date:string; weekday:number|null; day_of_month:number|null; status:string;
}
