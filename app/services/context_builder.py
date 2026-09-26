class ContextBuilder:
    def build(self, results):
        context_parts = []

        for result in results:
            context_parts.append(result["document"])

        return "\n\n".join(context_parts)