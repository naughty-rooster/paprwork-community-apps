#!/bin/bash
set -euo pipefail
GOOGLE_DB='/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db'
ADMIN_DB='/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db'
MY_EMAILS_REGEX='cbadcock@gmail\.com|corey@pivotvia\.com'
TOKEN=$(sqlite3 "$GOOGLE_DB" "SELECT t.access_token FROM oauth_tokens t JOIN connections c ON c.id=t.connection_id WHERE c.id='google:personal';")
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
api_get(){ curl --max-time 20 -sS -H "Authorization: Bearer $TOKEN" "$1"; }
sql_escape(){ printf "%s" "$1" | sed "s/'/''/g"; }
normalize_space(){ tr '\r' '\n' | sed 's/<[^>]*>/ /g; s/&nbsp;/ /g; s/&amp;/\&/g; s/&quot;/"/g; s/&#39;/'"'"'/g' | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//'; }
b64url_decode(){ local data="$1"; data="${data//-/+}"; data="${data//_/\/}"; local mod=$(( ${#data} % 4 )); if [ "$mod" -eq 2 ]; then data+="=="; elif [ "$mod" -eq 3 ]; then data+="="; fi; printf '%s' "$data" | base64 -D 2>/dev/null || true; }
message_text(){ local json="$1"; jq -r '
  def walkparts:. as $p|[$p]+(if ($p.parts?|type)=="array" then ([ $p.parts[]|walkparts ]|add) else [] end);
  .payload|walkparts|map(select((.mimeType//"")|test("^text/plain$|^text/html$")))|map(.body.data // empty)|.[]
' "$json" | while IFS= read -r enc; do b64url_decode "$enc"; printf '\n'; done | normalize_space | cut -c1-4000; }
infer_org(){
  local from="$1" org=""
  if printf '%s' "$from" | grep -q '<'; then
    org=$(printf '%s' "$from" | sed -E 's/[[:space:]]*<.*$//; s/^"//; s/"$//')
  elif printf '%s' "$from" | grep -q '@'; then
    org=$(printf '%s' "$from" | sed -E 's/.*@([A-Za-z0-9.-]+).*/\1/' | awk -F'.' '{print $(NF-1)}')
  fi
  org=$(printf '%s' "$org" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//; s/^no[._ -]*reply$//I')
  [ -z "$org" ] && org="Unknown"
  printf '%s' "$org" | sed 's/^./\U&/'
}
title_for(){
  local from="$1" subj="$2" body="$3" org blob title
  org=$(infer_org "$from")
  blob="$subj $body"
  shopt -s nocasematch
  if [[ "$blob" =~ (payment[[:space:]]due|pay[[:space:]]now|amount[[:space:]]due|past[[:space:]]due|overdraft|low[[:space:]]balance|invoice|bill) ]]; then
    title="Make a payment: $org"
  elif [[ "$blob" =~ (secure[[:space:]]message|please[[:space:]]respond|reply[[:space:]]to[[:space:]]this[[:space:]]email|respond[[:space:]]by|need[[:space:]]your[[:space:]]response|can[[:space:]]you[[:space:]]reply|verify[[:space:]]your[[:space:]]account) ]]; then
    title="Respond to message: $org"
  elif [[ "$blob" =~ (confirm[[:space:]]appointment|please[[:space:]]confirm|confirm[[:space:]]your[[:space:]]appointment|telehealth[[:space:]]appointment) ]]; then
    title="Confirm appointment: $org"
  elif [[ "$blob" =~ (upload|attach|please[[:space:]]send|provide[[:space:]](the[[:space:]])?(following|documents|information)|send[[:space:]]us) ]]; then
    if [[ "$blob" =~ upload|attach ]]; then title="Upload document: $org"; else title="Send information: $org"; fi
  elif [[ "$blob" =~ (submit|complete[[:space:]]form|fill[[:space:]]out|questionnaire|consent[[:space:]]form|intake[[:space:]]form) ]]; then
    title="Submit form: $org"
  elif [[ "$blob" =~ (review|signature[[:space:]]requested|please[[:space:]]sign|document[[:space:]]ready|filing|petition|motion|court|legal) ]]; then
    if [[ "$blob" =~ filing|petition|motion|court|legal ]]; then title="Review legal filing: $org"; else title="Review document: $org"; fi
  else
    title="Follow up with: $org"
  fi
  shopt -u nocasematch
  printf '%s' "$title"
}
needs_action(){
  local text="$1" subj="$2" blob
  blob="$subj $text"
  shopt -s nocasematch
  if [[ "$blob" =~ (newsletter|unsubscribe|promotion|sale|deal|discount|receipt|order[[:space:]]shipped|tracking[[:space:]]number|for[[:space:]]your[[:space:]]records|fyi|no[[:space:]]reply[[:space:]]needed|just[[:space:]]an[[:space:]]update|keep[[:space:]]an[[:space:]]eye[[:space:]]out|we[[:space:]]weren.t[[:space:]]able[[:space:]]to[[:space:]]locate|sounds[[:space:]]good|see[[:space:]]you[[:space:]]then|will[[:space:]]provide[[:space:]]an[[:space:]]update|thanks[[:space:]]got[[:space:]]it|paid|submitted|completed|done|taken[[:space:]]care[[:space:]]of|extension[[:space:]]filed|status[[:space:]]update|statement[[:space:]]is[[:space:]]available|payment[[:space:]]confirmation|payment[[:space:]]scheduled|membership[[:space:]]cancelled|membership[[:space:]]canceled|refund[[:space:]]is[[:space:]]confirmed|subscription[[:space:]]canceled|subscription[[:space:]]cancelled|activation[[:space:]]complete|data[[:space:]]sharing[[:space:]]enabled|you.re[[:space:]]now[[:space:]]sharing[[:space:]]data|final[[:space:]]confirmation|your[[:space:]]video[[:space:]]visit[[:space:]]starts) ]]; then
    shopt -u nocasematch; return 1
  fi
  if [[ "$blob" =~ (please[[:space:]]reply|please[[:space:]]respond|action[[:space:]]required|need[[:space:]]your[[:space:]]response|requires[[:space:]]your[[:space:]]attention|please[[:space:]]complete|please[[:space:]]submit|please[[:space:]]upload|please[[:space:]]review|please[[:space:]]sign|please[[:space:]]confirm|confirm[[:space:]]by|payment[[:space:]]due|pay[[:space:]]now|amount[[:space:]]due|past[[:space:]]due|overdraft|low[[:space:]]balance|send[[:space:]]us|provide[[:space:]]the[[:space:]]following|can[[:space:]]you[[:space:]]send|could[[:space:]]you[[:space:]]send|need[[:space:]]you[[:space:]]to|your[[:space:]]action[[:space:]]is[[:space:]]required|secure[[:space:]]message|verify[[:space:]]your[[:space:]]account|complete[[:space:]]intake|fill[[:space:]]out[[:space:]]the[[:space:]]form|questionnaire) ]]; then
    shopt -u nocasematch; return 0
  fi
  shopt -u nocasematch
  return 1
}
resolution_in_later_thread(){
  local thread_json="$1" cutoff_ms="$2"
  while IFS= read -r msg; do
    local from snippet subj labels blob
    from=$(jq -r '.from' <<<"$msg")
    snippet=$(jq -r '.snippet' <<<"$msg")
    subj=$(jq -r '.subj' <<<"$msg")
    labels=$(jq -r '.labels|join(",")' <<<"$msg")
    blob="$subj $snippet"
    if printf '%s' "$labels,$from" | grep -Eiq "SENT|$MY_EMAILS_REGEX"; then return 0; fi
    if printf '%s' "$blob" | grep -Eiq 'confirmed|filed|extension filed|done|completed|taken care of|scheduled|sounds good|see you then|paid|submitted|thanks got it'; then return 0; fi
  done < <(jq -c --argjson cutoff "$cutoff_ms" '
    .messages[] | select((.internalDate|tonumber) > $cutoff) |
    {from:([.payload.headers[]? | select(.name=="From")][0].value // ""),labels:(.labelIds // []),snippet:(.snippet // ""),subj:([.payload.headers[]? | select(.name=="Subject")][0].value // "")}
  ' "$thread_json")
  return 1
}
QUERY='in:inbox newer_than:4d -category:promotions -category:social'
QUERY_URI=$(jq -rn --arg q "$QUERY" '$q|@uri')
api_get "https://gmail.googleapis.com/gmail/v1/users/me/messages?q=${QUERY_URI}&maxResults=100" > "$TMPDIR/list.json"
jq -r '.messages[]?.threadId' "$TMPDIR/list.json" | awk '!seen[$0]++' | head -n 50 > "$TMPDIR/thread_ids.txt"
scanned=0 inserted=0
skip_duplicate=0 skip_no_action=0 skip_resolved=0 skip_similar=0 skip_calendar=0 skip_error=0 skip_old_done=0
while IFS= read -r thread_id; do
  [ -z "$thread_id" ] && continue
  tjson="$TMPDIR/thread-$thread_id.json"
  api_get "https://gmail.googleapis.com/gmail/v1/users/me/threads/$thread_id?format=full" > "$tjson"
  if jq -e '.error' "$tjson" >/dev/null; then skip_error=$((skip_error+1)); continue; fi
  candidate=$(jq -c --arg re "$MY_EMAILS_REGEX" '
    [.messages[]
      | {id,threadId,internalDate:(.internalDate|tonumber),labelIds:(.labelIds//[]),snippet:(.snippet//""),
         from:([.payload.headers[]? | select(.name=="From")][0].value // ""),
         subject:([.payload.headers[]? | select(.name=="Subject")][0].value // "")}
      | select((.labelIds|index("INBOX")) != null)
      | select((.from|test($re;"i"))|not)
    ] | sort_by(.internalDate) | reverse | .[0]
  ' "$tjson")
  [ "$candidate" = "null" ] && continue
  scanned=$((scanned+1))
  msg_id=$(jq -r '.id' <<<"$candidate")
  subject=$(jq -r '.subject' <<<"$candidate")
  from=$(jq -r '.from' <<<"$candidate")
  internal_ms=$(jq -r '.internalDate' <<<"$candidate")
  email_date=$(jq -r '.internalDate/1000 | strftime("%Y-%m-%dT%H:%M:%SZ")' <<<"$candidate")
  mjson="$TMPDIR/msg-$msg_id.json"
  jq -c --arg id "$msg_id" '.messages[] | select(.id==$id)' "$tjson" > "$mjson"
  body=$(message_text "$mjson")
  snippet=$(jq -r '.snippet' <<<"$candidate")
  blob="$subject $snippet $body"
  any_dup=$(sqlite3 "$ADMIN_DB" "SELECT COUNT(*) FROM tasks WHERE source='gmail' AND (gmail_message_id='$(sql_escape "$msg_id")' OR json_extract(source_details,'$.thread_id')='$(sql_escape "$thread_id")');")
  if [ "$any_dup" -gt 0 ]; then skip_duplicate=$((skip_duplicate+1)); continue; fi
  recent_done_same_sender=$(sqlite3 "$ADMIN_DB" "SELECT COUNT(*) FROM tasks WHERE source='gmail' AND status='done' AND lower(json_extract(source_details,'$.from'))=lower('$(sql_escape "$from")') AND created_at >= datetime('now','-7 day');")
  if [ "$recent_done_same_sender" -gt 0 ] && printf '%s' "$blob" | grep -Eiq 'confirmed|paid|scheduled|cancelled|canceled|submitted|done|completed|sounds good|see you then'; then skip_old_done=$((skip_old_done+1)); continue; fi
  if resolution_in_later_thread "$tjson" "$internal_ms"; then skip_resolved=$((skip_resolved+1)); continue; fi
  if ! needs_action "$body $snippet" "$subject"; then skip_no_action=$((skip_no_action+1)); continue; fi
  shopt -s nocasematch
  if [[ "$blob" =~ (appointment|telehealth|scheduled|calendar|invitation) ]] && [[ ! "$blob" =~ (please[[:space:]]confirm|confirm[[:space:]]your[[:space:]]appointment|complete[[:space:]]intake|fill[[:space:]]out|submit[[:space:]]forms|action[[:space:]]required) ]]; then
    skip_calendar=$((skip_calendar+1)); shopt -u nocasematch; continue
  fi
  shopt -u nocasematch
  title=$(title_for "$from" "$subject" "$body $snippet")
  similar_count=$(sqlite3 "$ADMIN_DB" "SELECT COUNT(*) FROM tasks WHERE source='gmail' AND status='open' AND created_at >= datetime('now','-10 day') AND lower(title)=lower('$(sql_escape "$title")') AND lower(json_extract(source_details,'$.from'))=lower('$(sql_escape "$from")');")
  if [ "$similar_count" -gt 0 ]; then skip_similar=$((skip_similar+1)); continue; fi
  desc=$(printf '%s' "$blob" | cut -c1-600)
  priority=2
  shopt -s nocasematch
  if [[ "$blob" =~ (overdraft|past[[:space:]]due|urgent|immediately|action[[:space:]]required|expires[[:space:]]today|deadline) ]]; then priority=1; fi
  shopt -u nocasematch
  if printf '%s' "$blob" | grep -Eiq 'overdraft|low balance|payment due|amount due'; then
    existing_finance=$(sqlite3 -separator $'\t' "$ADMIN_DB" "SELECT id, priority FROM tasks WHERE source='gmail' AND status='open' AND date(created_at)=date('now') AND lower(json_extract(source_details,'$.from'))=lower('$(sql_escape "$from")') AND lower(title) LIKE 'make a payment:%' ORDER BY priority ASC, id DESC LIMIT 1;")
    if [ -n "$existing_finance" ]; then
      existing_id=$(printf '%s' "$existing_finance" | cut -f1)
      existing_priority=$(printf '%s' "$existing_finance" | cut -f2)
      if [ "$existing_priority" -le "$priority" ]; then skip_similar=$((skip_similar+1)); continue; else sqlite3 "$ADMIN_DB" "UPDATE tasks SET status='done', updated_at=datetime('now') WHERE id=$existing_id;"; fi
    fi
  fi
  source_details=$(printf '{"subject":%s,"from":%s,"email_date":%s,"thread_id":%s}' \
    "$(jq -Rn --arg v "$subject" '$v')" \
    "$(jq -Rn --arg v "$from" '$v')" \
    "$(jq -Rn --arg v "$email_date" '$v')" \
    "$(jq -Rn --arg v "$thread_id" '$v')")
  sqlite3 "$ADMIN_DB" "INSERT INTO tasks (title, description, due_date, priority, status, source, gmail_message_id, source_details, created_at, updated_at) VALUES ('$(sql_escape "$title")','$(sql_escape "$desc")',NULL,$priority,'open','gmail','$(sql_escape "$msg_id")','$(sql_escape "$source_details")',datetime('now'),datetime('now'));"
  inserted=$((inserted+1))
done < "$TMPDIR/thread_ids.txt"
echo "scanned=$scanned inserted=$inserted skipped_duplicate=$skip_duplicate skipped_similar=$skip_similar skipped_resolved=$skip_resolved skipped_no_action=$skip_no_action skipped_calendar=$skip_calendar skipped_old_done=$skip_old_done skipped_error=$skip_error"