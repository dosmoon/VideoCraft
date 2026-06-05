; Custom NSIS include for VideoCraft — auto-picked up by electron-builder from
; buildResources (build/installer.nsh; see app-builder-lib NsisTarget.js).
;
; Purpose: preserve the install-local user_data/ across uninstall AND update.
;
; By design (desktop/electron/paths.ts) the packaged app keeps ALL user state
; beside the exe at $INSTDIR\user_data — downloaded ASR/LLM models (GB-scale),
; the embedded-AI runtime (user_data/runtimes/py-extra), settings.json, and the
; API keys + routing (user_data/keys; see core/ai/config.py keys_dir). This
; honours the portable-data rule (never %APPDATA%): the whole app folder is
; self-contained and can be zipped/moved.
;
; The default electron-builder uninstaller does `RMDir /r $INSTDIR`, and the
; update flow runs the OLD uninstaller before extracting the new app — so
; without this macro every reinstall/update would wipe the user's models, keys
; and settings. customRemoveFiles overrides that whole block: move user_data to
; a same-volume sibling, clear the app tree, then move it back. $INSTDIR's
; parent is on the same volume as $INSTDIR, so the Rename is an instant metadata
; move even for GB-scale model dirs (no copy, no cross-volume failure).
;
; Trade-off vs the default: we drop the default's atomic "rollback if a file is
; locked" rename. electron-builder's CHECK_APP_RUNNING already closes the app
; before this section, so in practice nothing in $INSTDIR is locked here.
;
; NOTE: this only protects updates FROM a build that carries this macro onward.
; The FIRST install over a pre-fix build runs the pre-fix uninstaller (no
; preserve) and still wipes — so the fixed build must be installed cleanly once.

!macro customRemoveFiles
  Push $0

  StrCpy $0 "$INSTDIR\..\VideoCraft-user_data.preserve"

  ; Stash user_data aside (same volume → instant), if present.
  ${if} ${FileExists} "$INSTDIR\user_data\*.*"
    RMDir /r "$0"                                   ; clear any stale stash
    Rename "$INSTDIR\user_data" "$0"
  ${endif}

  ; Clear the app payload (this is what the default block does).
  SetOutPath $TEMP
  RMDir /r $INSTDIR

  ; Restore user_data into the (now re-created) install dir.
  ${if} ${FileExists} "$0\*.*"
    CreateDirectory "$INSTDIR"
    Rename "$0" "$INSTDIR\user_data"
  ${endif}

  Pop $0
!macroend
