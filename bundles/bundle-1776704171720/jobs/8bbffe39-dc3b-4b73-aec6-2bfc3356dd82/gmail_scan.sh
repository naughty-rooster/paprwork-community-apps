#!/bin/bash
set -euo pipefail
OAUTH_DB='/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db'
ADMIN_DB='/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db'
TOKEN=$(sqlite3 "$OAUTH_DB" "SELECT access_token FROM oauth_tokens WHERE connection_id='google:personal';")
QUERY='in:inbox category:primary newer_than:4d -category:promotions -category:social'
USER_RE='(cbadcock@gmail\.com|coreybadcock@gmail\.com|corey@pivotvia\.com)'
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
SC=0; IN=0; SD=0; SR=0; SN=0; SS=0; SU=0; PT=''
clean(){ printf '%s' "$1" | tr '\r\n\t' '   ' | sed "s/&#39;/'/g;s/&amp;/\\&/g;s/  \+/ /g;s/^ //;s/ $//"; }
low(){ printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }
esc(){ printf '%s' "$1" | sed "s/'/''/g"; }
mail(){ printf '%s' "$1" | sed -n 's/.*<\([^>]*\)>.*/\1/p' | tr '[:upper:]' '[:lower:]'; }
name(){ local s; s=$(printf '%s' "$1" | sed 's/ <.*//;s/^"//;s/"$//;s/^ *//;s/ *$//'); [ -n "$s" ] && printf '%s' "$s" || printf '%s' "$1"; }
org(){ local f="$1" e d n; e=$(mail "$f"); d=${e#*@}; n=$(name "$f"); case "$d" in *demaarlaw.com*) echo 'de Maar Law';; *kingcounty.gov*) echo 'King County';; *mindfultherapygroup.com*|*advancedmd.com*) echo 'Mindful Therapy Group';; *fusionwebclinic.com*) echo 'Seattle Therapy';; *seattlecitylight.com*) echo 'Seattle City Light';; *dshs.wa.gov*) echo 'DSHS';; *morganstanley.com*) echo 'Morgan Stanley';; *) echo "$n";; esac; }
act(){ printf '%s' "$1" | grep -Eqi 'please (reply|respond|confirm|review|sign|submit|upload|send|provide|pay)|can you|could you|would you|let me know|what works|please let me know|action required|respond required|reply requested|payment due|balance due|past due|overdraft|low balance|review (the|this|attached)|orders filed|new orders filed|legal filing|secure message|complete (the|your)|submit (the|your)|upload (the|your)|fill out|sign (the|your)|confirm (your|the) appointment|please choose|please select|due by|deadline|urgent action|required by'; }
noact(){ printf '%s' "$1" | grep -Eqi 'newsletter|unsubscribe|receipt|order has shipped|tracking number|delivered|available now|statement is available|monthly statement|for your information|^fyi\b|just a reminder|your lab test results are now available|video visit is confirmed|starts in approximately|final confirmation|schedule change|availability|keep an eye out|will provide an update|we were(n.t| not) able to locate it|sounds good|see you then|payment received|thank you for your payment|lost and found|notification'; }
resolved(){ printf '%s' "$1" | grep -Eqi 'confirmed|filed|extension filed|done|completed|taken care of|scheduled|sounds good|see you then|paid|submitted|thanks[, ]+got it|payment received|received this email'; }
title(){ local o; o=$(org "$1"); case "$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')" in *payment
due*|*balance
due*|*past
due*|*overdraft*|*lowbalance*|*invoice*) echo "Make a payment: $o";; esac; if printf '%s' "$2" | grep -Eqi 'payment due|balance due|past due|overdraft|low balance|invoice'; then echo "Make a payment: $o"; elif printf '%s' "$2" | grep -Eqi 'orders filed|legal filing|case|court|motion|hearing'; then echo "Review legal filing: $o"; elif printf '%s' "$2" | grep -Eqi 'secure message'; then echo "Respond to secure message: $o"; elif printf '%s' "$2" | grep -Eqi 'confirm (your|the) appointment|what works|please choose|please select|telehealth|appointment'; then echo "Confirm appointment: $o"; elif printf '%s' "$2" | grep -Eqi 'upload'; then echo "Upload document: $o"; elif printf '%s' "$2" | grep -Eqi 'submit|fill out|application|form'; then echo "Submit form: $o"; elif printf '%s' "$2" | grep -Eqi 'send|provide'; then echo "Send information: $o"; elif printf '%s' "$2" | grep -Eqi 'review (the|this|attached)|document|attachment|statement'; then echo "Review document: $o"; else echo "Respond to message: $o"; fi; }
prio(){ printf '%s' "$1" | grep -Eqi 'past due|overdraft|legal filing|court|deadline|urgent action|required by' && echo 1 || echo 2; }
fetch(){ if [ -n "$1" ]; then curl -sS --fail -G 'https://gmail.googleapis.com/gmail/v1/users/me/messages' -H "Authorization: Bearer $TOKEN" --data-urlencode 'maxResults=100' --data-urlencode "q=$QUERY" --data-urlencode "pageToken=$1"; else curl -sS --fail -G 'https://gmail.googleapis.com/gmail/v1/users/me/messages' -H "Authorization: Bearer $TOKEN" --data-urlencode 'maxResults=100' --data-urlencode "q=$QUERY"; fi; }
: > "$TMP/cand.tsv"
while :; do
  PAGE=$(fetch "$PT")
  while IFS= read -r ROW; do
    MID=$(printf '%s' "$ROW" | base64 -d | jq -r '.id'); TID=$(printf '%s' "$ROW" | base64 -d | jq -r '.threadId'); SC=$((SC+1))
    [ "$(sqlite3 "$ADMIN_DB" "SELECT COUNT(1) FROM tasks WHERE source='gmail' AND gmail_message_id='$(esc "$MID")';")" = 0 ] || { SD=$((SD+1)); continue; }
    TF="$TMP/$TID.json"; [ -f "$TF" ] || curl -sS --fail -G "https://gmail.googleapis.com/gmail/v1/users/me/threads/$TID" -H "Authorization: Bearer $TOKEN" --data-urlencode 'format=metadata' --data-urlencode 'metadataHeaders=From' --data-urlencode 'metadataHeaders=Subject' --data-urlencode 'metadataHeaders=Date' --data-urlencode 'metadataHeaders=To' > "$TF"
    C=$(jq -r --arg m "$MID" '.messages[]|select(.id==$m)|{internalDate,snippet,headers:(.payload.headers|map({(.name):.value})|add)}|@base64' "$TF")
    [ -n "$C" ] || { SN=$((SN+1)); continue; }
    SENDER=$(printf '%s' "$C" | base64 -d | jq -r '.headers.From // ""'); SUBJ=$(printf '%s' "$C" | base64 -d | jq -r '.headers.Subject // ""'); EDATE=$(printf '%s' "$C" | base64 -d | jq -r '.headers.Date // ""'); SNIP=$(printf '%s' "$C" | base64 -d | jq -r '.snippet // ""'); TS=$(printf '%s' "$C" | base64 -d | jq -r '.internalDate // 0'); SEM=$(mail "$SENDER")
    printf '%s' "$SENDER" | grep -Eqi "$USER_RE" && { SU=$((SU+1)); continue; }
    TXT=$(low "$(clean "$SUBJ :: $SNIP")")
    LFROM=$(jq -r --argjson ts "$TS" '[.messages[]|{t:(.internalDate|tonumber),h:(.payload.headers|map({(.name):.value})|add)}|select(.t>$ts)|(.h.From//"")] | join("\n")' "$TF")
    LTEXT=$(jq -r --argjson ts "$TS" '[.messages[]|{t:(.internalDate|tonumber),s:(.snippet//""),h:(.payload.headers|map({(.name):.value})|add)}|select(.t>$ts)|((.h.Subject//"")+" :: "+.s)] | join("\n")' "$TF")
    [ -n "$LFROM" ] && printf '%s' "$LFROM" | grep -Eqi "$USER_RE" && { SR=$((SR+1)); continue; }
    [ -n "$LTEXT" ] && resolved "$LTEXT" && { SR=$((SR+1)); continue; }
    noact "$TXT" && ! act "$TXT" && { SN=$((SN+1)); continue; }
    act "$TXT" || { SN=$((SN+1)); continue; }
    TTL=$(title "$SENDER" "$TXT"); PRI=$(prio "$TXT"); DESC=$(clean "$SNIP")
    [ "$(sqlite3 "$ADMIN_DB" "SELECT COUNT(1) FROM tasks WHERE source='gmail' AND status='open' AND created_at>=datetime('now','-7 days') AND lower(COALESCE(json_extract(source_details,'$.from'),'')) LIKE '%$(esc "$SEM")%' AND lower(title)=lower('$(esc "$TTL")');")" = 0 ] || { SS=$((SS+1)); continue; }
    DKEY=$(date -j -f '%a, %d %b %Y %H:%M:%S %z' "$EDATE" '+%Y-%m-%d' 2>/dev/null || date -j -f '%a, %e %b %Y %H:%M:%S %z' "$EDATE" '+%Y-%m-%d' 2>/dev/null || echo '')
    SEV=0; FG=''; printf '%s' "$TXT" | grep -Eqi 'payment due|past due|balance due|overdraft' && { SEV=3; FG="$SEM|$DKEY|finance"; }; printf '%s' "$TXT" | grep -Eqi 'low balance' && { [ $SEV -lt 2 ] && SEV=2; FG="$SEM|$DKEY|finance"; }
    SJ=$(printf '{"subject":%s,"from":%s,"email_date":%s,"thread_id":%s}' "$(printf '%s' "$SUBJ" | jq -Rsa .)" "$(printf '%s' "$SENDER" | jq -Rsa .)" "$(printf '%s' "$EDATE" | jq -Rsa .)" "$(printf '%s' "$TID" | jq -Rsa .)")
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$SEV" "$FG" "$MID" "$TTL" "$DESC" "$PRI" "$SJ" >> "$TMP/cand.tsv"
  done < <(printf '%s' "$PAGE" | jq -r '.messages[]? | @base64')
  PT=$(printf '%s' "$PAGE" | jq -r '.nextPageToken // empty'); [ -n "$PT" ] || break
done
awk -F '\t' 'BEGIN{OFS="\t"}$2==""{print;next}{if(!($2 in b)||$1+0>s[$2]){b[$2]=$0;s[$2]=$1+0}}END{for(k in b)print b[k]}' "$TMP/cand.tsv" > "$TMP/final.tsv"
while IFS=$'\t' read -r SEV FG MID TTL DESC PRI SJ; do
  [ -n "$MID" ] || continue
  [ "$(sqlite3 "$ADMIN_DB" "SELECT COUNT(1) FROM tasks WHERE source='gmail' AND gmail_message_id='$(esc "$MID")';")" = 0 ] || continue
  sqlite3 "$ADMIN_DB" "INSERT INTO tasks (title,description,due_date,priority,status,source,gmail_message_id,source_details,created_at,updated_at) VALUES ('$(esc "$TTL")','$(esc "$DESC")',NULL,$PRI,'open','gmail','$(esc "$MID")','$(esc "$SJ")',datetime('now'),datetime('now'));"
  IN=$((IN+1))
done < "$TMP/final.tsv"
printf 'scanned=%s inserted=%s\n' "$SC" "$IN"
printf 'skipped: duplicate_message=%s similar_open=%s resolved_thread=%s non_action=%s sender_self=%s\n' "$SD" "$SS" "$SR" "$SN" "$SU"
[ -s "$TMP/final.tsv" ] && { echo 'inserted_titles:'; cut -f4 "$TMP/final.tsv" | sed '/^$/d;s/^/- /'; }
