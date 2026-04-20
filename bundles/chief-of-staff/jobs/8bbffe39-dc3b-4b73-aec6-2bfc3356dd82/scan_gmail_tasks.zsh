#!/bin/zsh
set -u
GOOGLE_DB='/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db'
ADMIN_DB='/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db'
WORK_DIR='/Users/coreybadcock/Papr/jobs/8bbffe39-dc3b-4b73-aec6-2bfc3356dd82/tmp_gmail_scan'
mkdir -p "$WORK_DIR"
ACCESS_TOKEN=$(sqlite3 "$GOOGLE_DB" "select access_token from oauth_tokens where connection_id='google:personal';")
SELF_EMAIL='cbadcock@gmail.com'
QUERY='newer_than:4d in:inbox -category:promotions -category:social'
[[ -n "$ACCESS_TOKEN" ]] || { echo 'No access token'; exit 1; }
api_get(){ curl -fsS -H "Authorization: Bearer $ACCESS_TOKEN" "$1"; }
header(){ jq -r --arg n "$1" '[..|objects|select(has("headers"))|.headers[]|select(.name==$n)|.value][0] // ""'; }
plain_b64(){ jq -r '[..|objects|select(((.mimeType // "") == "text/plain") and ((.body.data // "") != ""))|.body.data] | join("\n")'; }
dec(){ local s="$1"; [[ -z "$s" || "$s" == null ]] && return 0; local pad=$(( (4 - ${#s} % 4) % 4 )); s=${s//-/+}; s=${s//_/\/}; print -n -- "$s$(printf '=%.0s' {1..4} | cut -c1-$pad)" | base64 -d 2>/dev/null || true; }
clean(){ tr '\r' '\n' | sed 's/<[^>]*>/ /g; s/&nbsp;/ /g; s/&amp;/\&/g' | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//'; }
sender_name(){ local from="$1" n e d b; n=$(print -r -- "$from" | sed -E 's/^\"?([^\"<]+)\"?[[:space:]]*<.*$/\1/; t; s/@.*//'); e=$(print -r -- "$from" | sed -nE 's/.*<([^>]+)>.*/\1/p'); [[ -z "$e" ]] && e=$(print -r -- "$from" | grep -Eo '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+' | head -n1 || true); d=$(print -r -- "$e" | awk -F'@' '{print $2}'); b=$(print -r -- "$d" | awk -F. '{print $(NF-1)}'); [[ -n "$n" && "$n" != "$from" ]] && print -r -- "$n" | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//' || ([[ -n "$b" ]] && print -r -- "$b" | sed 's/-/ /g' || print 'Unknown'); }
contains(){ print -r -- "$1" | grep -Eqi "$2"; }
normalize_title(){ local subject="$1" from="$2" body="$3" who lc; who=$(sender_name "$from"); lc=$(print -r -- "$subject $body" | tr '[:upper:]' '[:lower:]'); if contains "$lc" 'payment due|amount due|pay now|past due|overdraft|negative balance|low balance|invoice|bill due|statement available'; then print "Make a payment: $who"; elif contains "$lc" 'secure message|please reply|reply requested|respond|your response|can you|could you|please let us know|let me know'; then print "Respond to message: $who"; elif contains "$lc" 'telehealth|appointment confirmation|required.*confirm|confirm.*appointment|verify appointment'; then print "Confirm appointment: $who"; elif contains "$lc" 'upload|attach.*document|provide.*document|send.*document|proof of|verification document'; then print "Upload document: $who"; elif contains "$lc" 'submit|complete.*form|fill out|questionnaire|survey|consent form|waiver'; then print "Submit form: $who"; elif contains "$lc" 'send.*information|provide.*information|need.*information|share.*information'; then print "Send information: $who"; elif contains "$lc" 'court|filing|petition|motion|declaration|legal'; then print "Review legal filing: $who"; elif contains "$lc" 'document|review attached|please review|attached for your review|statement available'; then print "Review document: $who"; else print "Follow up with: $who"; fi }
priority_for(){ local lc; lc=$(print -r -- "$1 $2" | tr '[:upper:]' '[:lower:]'); contains "$lc" 'overdraft|negative balance|past due|urgent|immediately|deadline|court|hearing|legal|payment due|final notice' && print 1 || print 2; }
marketing(){ contains "$1" 'unsubscribe|view in browser|manage preferences|sale|special offer|promo|newsletter|receipt|order confirmation|shipped|delivered|tracking number|marketing|advertisement'; }
actionable(){ contains "$1" 'please (reply|respond|confirm|review|sign|complete|submit|upload|send|provide|pay|let us know)|action required|your response is required|required to|can you|could you|we need you to|payment due|amount due|past due|overdraft|negative balance|complete the form|fill out|review attached|sign and return|send .* to us|provide .* by'; }
resolved_text(){ contains "$1" 'confirmed|filed|extension filed|done|completed|taken care of|scheduled|sounds good|see you then|paid|submitted|thanks[, ]+got it|got it, thanks|we received|all set|final confirmation'; }
explicit_skip(){ contains "$1" 'will provide an update|keep an eye out|we were not able to locate it|sounds good|see you then|for your information|fyi|just a reminder|status update|availability notice|no reply needed'; }
similar_exists(){ local msg="$1" from="$2" title="$3" thread="$4"; local me=${msg//\'/\'\'} fe=${from//\'/\'\'} te=${title//\'/\'\'} th=${thread//\'/\'\'}; local c=$(sqlite3 "$ADMIN_DB" "select count(*) from tasks where status='open' and source='gmail' and (gmail_message_id='$me' or json_extract(source_details,'$.thread_id')='$th' or (lower(title)=lower('$te') and lower(coalesce(json_extract(source_details,'$.from'),''))=lower('$fe') and datetime(created_at)>=datetime('now','-14 days')));"); [[ "$c" -gt 0 ]]; }
rm -f "$WORK_DIR"/*.tsv "$WORK_DIR"/seen_threads.txt
LIST=$(curl -fsS -G -H "Authorization: Bearer $ACCESS_TOKEN" --data-urlencode "q=$QUERY" --data-urlencode 'maxResults=100' 'https://gmail.googleapis.com/gmail/v1/users/me/messages')
print -r -- "$LIST" > "$WORK_DIR/list.json"
scanned=0; inserted=0; skip_duplicates=0; skip_no_action=0; skip_resolved=0; skip_noise=0; skip_finance_weaker=0; skip_errors=0
while IFS=$'\t' read -r msg_id thread_id; do
  [[ -z "$msg_id" || -z "$thread_id" ]] && continue
  grep -qx "$thread_id" "$WORK_DIR/seen_threads.txt" 2>/dev/null && continue
  print -r -- "$thread_id" >> "$WORK_DIR/seen_threads.txt"
  scanned=$((scanned+1))
  thread_json=$(api_get "https://gmail.googleapis.com/gmail/v1/users/me/threads/$thread_id?format=full") || { skip_errors=$((skip_errors+1)); continue; }
  cand=$(print -r -- "$thread_json" | jq -c --arg id "$msg_id" '.messages[] | select(.id==$id)')
  [[ -z "$cand" ]] && { skip_errors=$((skip_errors+1)); continue; }
  from=$(print -r -- "$cand" | header 'From' | clean)
  subject=$(print -r -- "$cand" | header 'Subject' | clean)
  date_hdr=$(print -r -- "$cand" | header 'Date' | clean)
  snippet=$(print -r -- "$cand" | jq -r '.snippet // ""' | clean)
  body=$(dec "$(print -r -- "$cand" | plain_b64)" | clean)
  text=$(print -r -- "$subject $snippet $body" | clean)
  contains "$from" "$SELF_EMAIL|Corey Badcock" && { skip_no_action=$((skip_no_action+1)); continue; }
  marketing "$text" && { skip_noise=$((skip_noise+1)); continue; }
  explicit_skip "$text" && { skip_no_action=$((skip_no_action+1)); continue; }
  actionable "$text" || { skip_no_action=$((skip_no_action+1)); continue; }
  ask_ts=$(print -r -- "$cand" | jq -r '.internalDate // 0')
  resolved=0
  while IFS= read -r msg; do
    m_ts=$(print -r -- "$msg" | jq -r '.internalDate // 0')
    if (( m_ts > ask_ts )); then
      m_from=$(print -r -- "$msg" | header 'From' | clean)
      m_snip=$(print -r -- "$msg" | jq -r '.snippet // ""' | clean)
      m_body=$(dec "$(print -r -- "$msg" | plain_b64)" | clean)
      m_text=$(print -r -- "$m_snip $m_body" | clean)
      contains "$m_from" "$SELF_EMAIL|Corey Badcock" && resolved=1
      resolved_text "$m_text" && resolved=1
    fi
  done < <(print -r -- "$thread_json" | jq -c '.messages[]')
  (( resolved )) && { skip_resolved=$((skip_resolved+1)); continue; }
  title=$(normalize_title "$subject" "$from" "$text")
  priority=$(priority_for "$subject" "$text")
  similar_exists "$msg_id" "$from" "$title" "$thread_id" && { skip_duplicates=$((skip_duplicates+1)); continue; }
  description=$(print -r -- "From $from on $date_hdr. $snippet" | cut -c1-500)
  print -r -- "$msg_id	$thread_id	$from	$date_hdr	$subject	$title	$description	$priority	$text" >> "$WORK_DIR/candidates.tsv"
done < <(jq -r '.messages[]? | [.id,.threadId] | @tsv' "$WORK_DIR/list.json")
[[ -f "$WORK_DIR/candidates.tsv" ]] || touch "$WORK_DIR/candidates.tsv"
while IFS=$'\t' read -r msg_id thread_id from date_hdr subject title description priority text; do
  lc=$(print -r -- "$subject $text" | tr '[:upper:]' '[:lower:]')
  if contains "$lc" 'overdraft|negative balance|low balance|payment due|past due|statement available'; then
    day=$(date -j -f '%a, %d %b %Y %T %z' "$date_hdr" '+%Y-%m-%d' 2>/dev/null || print -r -- "$date_hdr" | grep -Eo '^[0-9]{4}-[0-9]{2}-[0-9]{2}' || print unknown)
    key="$(print -r -- "$from" | tr '[:upper:]' '[:lower:]')|$day"
    score=1; contains "$lc" 'overdraft|negative balance' && score=3; contains "$lc" 'past due|payment due' && score=2
    old=$(grep -F "$key" "$WORK_DIR/finance.tsv" 2>/dev/null | tail -n1 || true)
    if [[ -z "$old" ]]; then
      print -r -- "$key	$score	$msg_id" >> "$WORK_DIR/finance.tsv"
      print -r -- "$msg_id	$thread_id	$from	$date_hdr	$subject	$title	$description	$priority" >> "$WORK_DIR/final.tsv"
    else
      old_score=$(print -r -- "$old" | awk -F'\t' '{print $2}')
      old_id=$(print -r -- "$old" | awk -F'\t' '{print $3}')
      if (( score > old_score )); then
        awk -F'\t' -v id="$old_id" '$1!=id' "$WORK_DIR/final.tsv" > "$WORK_DIR/final2.tsv" && mv "$WORK_DIR/final2.tsv" "$WORK_DIR/final.tsv"
        print -r -- "$key	$score	$msg_id" >> "$WORK_DIR/finance.tsv"
        print -r -- "$msg_id	$thread_id	$from	$date_hdr	$subject	$title	$description	$priority" >> "$WORK_DIR/final.tsv"
        skip_finance_weaker=$((skip_finance_weaker+1))
      else
        skip_finance_weaker=$((skip_finance_weaker+1))
      fi
    fi
  else
    print -r -- "$msg_id	$thread_id	$from	$date_hdr	$subject	$title	$description	$priority" >> "$WORK_DIR/final.tsv"
  fi
done < "$WORK_DIR/candidates.tsv"
[[ -f "$WORK_DIR/final.tsv" ]] || touch "$WORK_DIR/final.tsv"
while IFS=$'\t' read -r msg_id thread_id from date_hdr subject title description priority; do
  [[ -z "$msg_id" ]] && continue
  m=${msg_id//\'/\'\'}; th=${thread_id//\'/\'\'}; fr=${from//\'/\'\'}; dt=${date_hdr//\'/\'\'}; su=${subject//\'/\'\'}; ti=${title//\'/\'\'}; de=${description//\'/\'\'}
  sqlite3 "$ADMIN_DB" "insert into tasks (title,description,due_date,priority,status,source,gmail_message_id,source_details) values ('$ti','$de',NULL,$priority,'open','gmail','$m',json_object('subject','$su','from','$fr','email_date','$dt','thread_id','$th'));"
  inserted=$((inserted+1))
done < "$WORK_DIR/final.tsv"
print "scanned_count=$scanned"
print "inserted_count=$inserted"
print "skipped_duplicates=$skip_duplicates"
print "skipped_no_action=$skip_no_action"
print "skipped_resolved=$skip_resolved"
print "skipped_noise=$skip_noise"
print "skipped_finance_weaker=$skip_finance_weaker"
print "skipped_errors=$skip_errors"
[[ -s "$WORK_DIR/final.tsv" ]] && { print 'inserted_titles:'; awk -F'\t' '{print "- " $6 " [" $1 "]"}' "$WORK_DIR/final.tsv"; }
