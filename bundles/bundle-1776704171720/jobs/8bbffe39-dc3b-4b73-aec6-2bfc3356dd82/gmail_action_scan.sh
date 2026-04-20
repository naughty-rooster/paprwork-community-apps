#!/bin/bash
set -euo pipefail
GOOGLE_DB='/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db'
ADMIN_DB='/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db'
SELF_EMAIL='cbadcock@gmail.com'
DRY_RUN="${DRY_RUN:-1}"
ACCESS_TOKEN=$(sqlite3 "$GOOGLE_DB" "SELECT access_token FROM oauth_tokens WHERE connection_id='google:personal';")
QUERY='in:inbox newer_than:4d -category:promotions -category:social'

clean_text() {
  printf '%s' "$1" | perl -MHTML::Entities -pe 'decode_entities($_)' | tr '\n' ' ' | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//'
}

sender_name() {
  printf '%s' "$1" | sed -E 's/ <.*//; s/^"//; s/"$//; s/^ +//; s/ +$//'
}

sender_org() {
  local name
  name=$(sender_name "$1")
  case "$name" in
    MINDFUL\ THERAPY\ GROUP\ WASHINGTON|Mindful\ Support\ Services) echo 'Mindful Therapy Group' ;;
    Ensora\ Health\ Automated\ Email) echo 'Seattle Therapy' ;;
    MORGAN\ STANLEY|Morgan\ Stanley) echo 'Morgan Stanley' ;;
    Family\ Law\ Staff\ Seattle) echo 'King County Family Law' ;;
    Broadview\ ELDC) echo 'Broadview ELDC' ;;
    no-reply@seattle.gov) echo 'Seattle City Light' ;;
    *) echo "$name" ;;
  esac
}

classify_title() {
  local org="$1" text="$2" subject="$3"
  local ltext
  ltext=$(printf '%s %s' "$subject" "$text" | tr '[:upper:]' '[:lower:]')
  if [[ "$ltext" =~ (security.alert|new.sign.in|wasn.t.you|if.you.don.t.recognize|remove.it|update.your.account.password) ]]; then
    echo "Review security alert: $org|Review recent security alert from $org and secure the account if the sign-in was not yours.|1"
  elif [[ "$ltext" =~ (payment.due|past.due|overdraft|low.balance|bill.due|amount.due) ]]; then
    echo "Make a payment: $org|Review the billing email from $org and make any required payment.|1"
  elif [[ "$ltext" =~ (proxyvote|vote.now|annual.meeting) ]]; then
    echo "Review proxy vote: $org|Review the shareholder voting email from $org and submit a vote if needed.|3"
  elif [[ "$ltext" =~ (document.from|new.message.waiting|review.the.attached|progress.note|you.have.received.a.document) ]]; then
    echo "Review document: $org|Review the document sent by $org and take any follow-up action if needed.|2"
  elif [[ "$ltext" =~ (secure.message|please.reply|can.you|could.you|let.me.know|need.your|awaiting.your|review.and.respond) ]]; then
    echo "Respond to message: $org|Review the latest message from $org and respond if needed.|2"
  elif [[ "$ltext" =~ (confirm.appointment|appointment.check-in|complete.check-in|telehealth.appointment|confirm.your.appointment) ]]; then
    echo "Confirm appointment: $org|Review the appointment email from $org and complete any required confirmation or check-in.|2"
  elif [[ "$ltext" =~ (submit.form|complete.form|fill.out|questionnaire) ]]; then
    echo "Submit form: $org|Complete the requested form for $org.|2"
  elif [[ "$ltext" =~ (upload|attach|send.over|send.the.following|provide.the.following) ]]; then
    echo "Send information: $org|Review the request from $org and send the needed information.|2"
  else
    return 1
  fi
}

skip_reason() {
  local text="$1"
  local ltext
  ltext=$(printf '%s' "$text" | tr '[:upper:]' '[:lower:]')
  if [[ "$ltext" =~ (verification.code|mfa.code|sign.in.link|one-time.sign.in.link|authentication.code) ]]; then echo otp_or_signin; return; fi
  if [[ "$ltext" =~ (automatic.reply|out.of.office|on.leave) ]]; then echo auto_reply; return; fi
  if [[ "$ltext" =~ (order.receipt|receipt|payment.confirmation|payment.scheduled|thank.you.for.your.recent.*payment|your.google.play.order) ]]; then echo receipt_or_confirmation; return; fi
  if [[ "$ltext" =~ (will.provide.an.update|keep.an.eye.out|we.weren.t.able.to.locate.it|sounds.good|see.you.then|thank.you.for.your.follow.up.and.patience) ]]; then echo status_only; return; fi
  if [[ "$ltext" =~ (teacher.appreciation.week|activate.your.streaming.subscriptions|eligible.to.move.your.available.credit.line|updates$|launch.team|concert|invitation) ]]; then echo newsletter_or_marketing; return; fi
  if [[ "$ltext" =~ (final.confirmation|schedule.change|game.times) ]]; then echo informational_only; return; fi
  return 1
}

similar_open_exists() {
  local sender="$1"
  sqlite3 "$ADMIN_DB" "SELECT COUNT(*) FROM tasks WHERE source='gmail' AND status='open' AND json_extract(source_details,'$.from')=$(printf "%q" "$sender") AND created_at >= datetime('now','-7 days');" 2>/dev/null
}

LIST_JSON=$(mktemp)
curl -sS -H "Authorization: Bearer $ACCESS_TOKEN" --get 'https://gmail.googleapis.com/gmail/v1/users/me/messages' \
  --data-urlencode "q=$QUERY" --data-urlencode 'maxResults=100' > "$LIST_JSON"
THREADS=$(jq -r '.messages[]?.threadId' "$LIST_JSON" | awk '!seen[$0]++')
scanned=0
inserted=0
skip_duplicate=0
skip_existing_thread=0
skip_existing_sender=0
skip_outbound=0
skip_nonaction=0
skip_resolved=0
skip_other=0
insert_log=()

for tid in $THREADS; do
  scanned=$((scanned+1))
  THREAD_JSON=$(mktemp)
  curl -sS -H "Authorization: Bearer $ACCESS_TOKEN" --get "https://gmail.googleapis.com/gmail/v1/users/me/threads/$tid" \
    --data-urlencode 'format=metadata' \
    --data-urlencode 'metadataHeaders=Subject' \
    --data-urlencode 'metadataHeaders=From' \
    --data-urlencode 'metadataHeaders=Date' > "$THREAD_JSON"

  latest=$(jq -r '
    .messages | sort_by(.internalDate|tonumber) | last |
    [
      .id,
      .threadId,
      ((.payload.headers[]|select(.name=="From")|.value) // ""),
      ((.payload.headers[]|select(.name=="Subject")|.value) // ""),
      ((.payload.headers[]|select(.name=="Date")|.value) // ""),
      .snippet,
      (.labelIds|join(","))
    ] | @tsv' "$THREAD_JSON")

  IFS=$'\t' read -r msg_id thread_id from subject email_date snippet labels <<< "$latest"
  full_text=$(clean_text "$subject $snippet")
  lower=$(printf '%s' "$full_text" | tr '[:upper:]' '[:lower:]')

  if [[ "$from" == *"$SELF_EMAIL"* ]]; then skip_outbound=$((skip_outbound+1)); rm -f "$THREAD_JSON"; continue; fi

  if [[ $(sqlite3 "$ADMIN_DB" "SELECT COUNT(*) FROM tasks WHERE gmail_message_id='$msg_id';") -gt 0 ]]; then skip_duplicate=$((skip_duplicate+1)); rm -f "$THREAD_JSON"; continue; fi
  if [[ $(sqlite3 "$ADMIN_DB" "SELECT COUNT(*) FROM tasks WHERE source='gmail' AND json_extract(source_details,'$.thread_id')='$thread_id';") -gt 0 ]]; then skip_existing_thread=$((skip_existing_thread+1)); rm -f "$THREAD_JSON"; continue; fi

  if reason=$(skip_reason "$lower"); then
    skip_nonaction=$((skip_nonaction+1))
    rm -f "$THREAD_JSON"
    continue
  fi

  if [[ "$lower" =~ (confirmed|extension.filed|done|completed|taken.care.of|scheduled|sounds.good|see.you.then|paid|submitted|thanks.got.it) ]]; then
    skip_resolved=$((skip_resolved+1)); rm -f "$THREAD_JSON"; continue
  fi

  org=$(sender_org "$from")
  if ! pack=$(classify_title "$org" "$snippet" "$subject"); then
    skip_nonaction=$((skip_nonaction+1)); rm -f "$THREAD_JSON"; continue
  fi
  IFS='|' read -r title description priority <<< "$pack"

  sender_open=$(sqlite3 "$ADMIN_DB" "SELECT COUNT(*) FROM tasks WHERE source='gmail' AND status='open' AND json_extract(source_details,'$.from') = '$from' AND created_at >= datetime('now','-7 days');")
  if [[ "$sender_open" -gt 0 ]]; then skip_existing_sender=$((skip_existing_sender+1)); rm -f "$THREAD_JSON"; continue; fi

  source_details=$(jq -cn --arg subject "$subject" --arg from "$from" --arg email_date "$email_date" --arg thread_id "$thread_id" '{subject:$subject,from:$from,email_date:$email_date,thread_id:$thread_id}')
  desc_full=$(clean_text "$description Subject: $subject. From: $from. Preview: $snippet")

  if [[ "$DRY_RUN" == "0" ]]; then
    sqlite3 "$ADMIN_DB" <<SQL
.parameter init
.parameter set @title '$title'
.parameter set @description '$desc_full'
.parameter set @priority '$priority'
.parameter set @gmail_message_id '$msg_id'
.parameter set @source_details '$source_details'
INSERT INTO tasks (title, description, due_date, priority, status, source, gmail_message_id, source_details)
VALUES (@title, @description, NULL, @priority, 'open', 'gmail', @gmail_message_id, @source_details);
SQL
  fi
  inserted=$((inserted+1))
  insert_log+=("$title | $from | $email_date")
  rm -f "$THREAD_JSON"
done

printf 'scanned=%s\n' "$scanned"
printf 'inserted=%s\n' "$inserted"
printf 'skipped: duplicate_message=%s existing_thread=%s existing_sender_open=%s outbound_latest=%s non_action=%s resolved=%s other=%s\n' \
  "$skip_duplicate" "$skip_existing_thread" "$skip_existing_sender" "$skip_outbound" "$skip_nonaction" "$skip_resolved" "$skip_other"
if ((${#insert_log[@]})); then
  printf 'inserted_titles:\n'
  printf ' - %s\n' "${insert_log[@]}"
fi
