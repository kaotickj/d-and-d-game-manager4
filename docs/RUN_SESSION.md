# Run Session

Open **Run Session** from the main window, Campaign Tools menu, or **Ctrl+R**.
The modeless dashboard brings the active campaign party, current scene,
initiative, encounter HP, dice and session quick notes together. It shares the
existing scene and Battle Trakker controller; it does not create another save
format or a separate copy of combat state.

**Party & Scene** shows saved party references and the live scene. Party
membership does not imply presence in the scene or combat. **Add party** adds
party members to the scene explicitly; **Add scene roster** adds missing
instances to the current encounter. These actions preserve permanent creature
records. Duplicate combat instances already present remain independent.

**Combat** shows the current turn, initiative, HP, conditions and recent log.
Select a combatant before applying damage or healing. Roll initiative, start
combat or advance a turn with explicit buttons. Each action saves through the
existing encounter store; a failed save rolls back that dashboard action.
Open the full Battle desk for advanced attacks, spells and effect clocks.

**Rolls & Notes** supports ordinary dice expressions and visible physical die
results, including outside combat. A roll alone does not create an encounter or
change the journal. Quick notes append only when **Append to Session** is
clicked; they use the selected session's existing Notes field. Plans, notes and
reviewed recaps remain separate. The dashboard is a private DM tool, not a
player display.

If another editor changes session notes, the append is rejected and the draft
is kept. Use **Review latest notes**, inspect the current journal, then retry.
Live refresh never rebases an unsaved draft automatically. Changing workspace
or closing with an unsaved note offers Save, Discard or Cancel. Invalid reads,
stale notes and failed saves keep the draft available.

Opening or refreshing the dashboard does not create encounters, roll dice,
write notes, advance time or change character sheets. The active installed
v0.10.0 application will gain this dashboard only after installing a build that
contains this change; source development does not update a running application.
