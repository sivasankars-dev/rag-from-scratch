class ContextBuilder:
    def build(self, results):
        documents = results["documents"][0]

        return "\n\n".join(documents)