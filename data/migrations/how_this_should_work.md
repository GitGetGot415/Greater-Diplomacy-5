ok so tldr

for research, it should be based on the research year you have

so for example if you have 1917 infantry researched in v46 this should translate to you having 1914 trench infantry I in v47

if you have 1918 infantry researched in v46 then that translates to you having 1918 trench infantry II in v47

for units, if a unit is 1917 infantry in v46, convert it to 1914 trench infantry I in v47

the stats should be changed as well, though % of hp should remain the same

ideally this should allow for conversions to be less hardcoded and able to handle a broader amount of changes instead of being specific to certain versions

also maybe instead of keeping dedicated version handling for handling tournament moves or older saves and such it's more general so this doesn't have to be updated as often

perhaps instead of tests related to migration being just thrown in the test folder, it can be thrown in the migrations folder so they aren't run unless dealing with migration specifically, since migration doesn't really apply when playing / working on the current game so much as it applies when handling older saves / files