.PHONY: help install setup dev dev-app dev-agent dev-mcp build lint clean

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install all dependencies (Node + Python)
	pnpm install

setup: install ## Full setup: install deps and create env files from templates
	cd apps/agent && uv sync
	pnpm --filter @repo/design-system build
	@if [ ! -f apps/agent/.env ]; then \
		cp apps/agent/.env.example apps/agent/.env; \
		echo "Created apps/agent/.env — add your ANTHROPIC_API_KEY (or OpenAI key)"; \
	else \
		echo "apps/agent/.env already exists, skipping"; \
	fi
	@if [ ! -f apps/app/.env.local ]; then \
		cp apps/app/.env.example apps/app/.env.local; \
		echo "Created apps/app/.env.local"; \
	else \
		echo "apps/app/.env.local already exists, skipping"; \
	fi

dev: ## Start the UI (http://localhost:3000) and the agent
	pnpm dev

dev-app: ## Start Next.js frontend only (http://localhost:3000)
	pnpm dev:app

dev-agent: ## Start LangGraph agent only (http://localhost:8123)
	pnpm dev:agent

dev-mcp: ## Start MCP server only
	pnpm dev:mcp

build: ## Build all apps
	pnpm build

lint: ## Lint all apps
	pnpm lint

clean: ## Clean build artifacts
	pnpm clean
