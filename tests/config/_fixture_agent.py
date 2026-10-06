class EchoAgent:
    def run(self, task, config, seed):
        return {"final_message": f"echo:{task.task_id}:{config.get('model')}"}


echo_agent = EchoAgent()
