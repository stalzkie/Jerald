class ConditionalAgent:
    def run(self, task, config, seed):
        message = "ok" if config.get("model") == "baseline-model" else "bad"
        return {"final_message": message}


agent = ConditionalAgent()
