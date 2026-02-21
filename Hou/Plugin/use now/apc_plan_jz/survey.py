# my_apc_script.py  (ONLY the update_survey() part you add/replace)
# -*- coding: utf-8 -*-
# Hussein Al Shibli  |  BGP Oman APC

def update_survey(self):
    """
    Survey ↻ button action
    Calls survey.py inside plugin folder.
    """
    try:
        self.status.setText("Survey ↻ : Starting...")
        info("Survey ↻ clicked.")

        # ✅ Load survey.py from the plugin folder (works even without package imports)
        import importlib.util

        plugin_dir = os.path.dirname(__file__)
        survey_path = os.path.join(plugin_dir, "survey.py")

        if not os.path.exists(survey_path):
            msg = f"survey.py not found in plugin folder: {survey_path}"
            warn(msg)
            self.status.setText(f"Survey ↻ : {msg}")
            return

        spec = importlib.util.spec_from_file_location("apc_survey", survey_path)
        survey = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(survey)

        ok, msg = survey.run(
            iface=iface,
            parent=self,
            status_callback=self.status.setText
        )

        if ok:
            self.status.setText(msg)
            info(msg)
        else:
            self.status.setText(msg)
            warn(msg)

    except Exception as e:
        log_exc("Update Survey failed", e)
        self.status.setText(f"Survey ↻ : Error: {e}")

# Hussein Al Shibli | BGP Oman APC
