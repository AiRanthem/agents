# Optional Aone mirror

Enable Aone only for the selected project configuration and authorized external scope. Project files contain complete requirements, design and evidence. The mirror contains configured title, status, body and fields; use `【项目名】` in titles when that is the project's naming convention. Keep credentials outside project records.

Use available authenticated Aone service tools. Read the existing space, item type, required fields and status mapping before using them. Record actual external item IDs/URLs. Missing service access or an unknown required field is unresolved input, not successful synchronization.

Update configured managed fields and preserve unrelated external content. Confirm the service's actual result before recording synchronization as complete. Status transitions and body edits can have separate outcomes; report what succeeded and what remains unresolved.

If a creation response is uncertain, search the service by known project/item identity before retrying. Adopt only an unambiguous matching item. Keep unresolved outcomes and useful response evidence in `.project/sync/<id>.yaml` or item context to avoid duplicate creation.

Commit and push the resulting project records. Report Git publication and Aone synchronization separately; neither substitutes for the other.
