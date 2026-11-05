class Captain::RewriteService < Captain::BaseTaskService
  pattr_initialize [:account!, :content!, :operation!, { conversation_display_id: nil }]

  TONE_OPERATIONS = %i[casual professional friendly confident straightforward].freeze
  EEU_OPERATIONS = %i[formal_amharic polite_oromoo polite_tigrinya technical_clarity empathetic_deescalation].freeze
  ALLOWED_OPERATIONS = (%i[fix_spelling_grammar improve] + TONE_OPERATIONS + EEU_OPERATIONS).freeze

  def perform
    operation_sym = operation.to_sym
    raise ArgumentError, "Invalid operation: #{operation}" unless ALLOWED_OPERATIONS.include?(operation_sym)

    send(operation_sym)
  end

  TONE_OPERATIONS.each do |tone|
    define_method(tone) do
      call_llm_with_prompt(tone_rewrite_prompt(tone.to_s))
    end
  end

  EEU_OPERATIONS.each do |tone|
    define_method(tone) do
      rewrite_via_eeu_engine(tone.to_s)
    end
  end

  private

  def rewrite_via_eeu_engine(tone)
    candidate_urls = [
      ENV['EEU_AI_GATEWAY_URL'],
      'http://eeu-ai-pilot-gateway-1:4000',
      'http://127.0.0.1:4000'
    ].compact.uniq

    candidate_urls.each do |base_url|
      response = call_eeu_gateway(base_url, tone)
      return response if response
    end

    call_llm_with_prompt(tone_rewrite_prompt(tone))
  end

  def call_eeu_gateway(base_url, tone)
    uri = URI("#{base_url}/api/v1/rewrite")
    http = Net::HTTP.new(uri.host, uri.port)
    http.read_timeout = 5
    http.open_timeout = 2
    req = Net::HTTP::Post.new(uri.path, { 'Content-Type' => 'application/json' })
    req.body = { content: content, operation: tone, tone: tone }.to_json
    res = http.request(req)
    if res.is_a?(Net::HTTPSuccess)
      data = JSON.parse(res.body)
      { message: data['message'] || data['rewritten_text'] }
    end
  rescue StandardError => e
    Rails.logger.warn("[EEU AI Gateway] Rewrite call to #{uri} failed: #{e.message}. Falling back to LLM prompt.")
    nil
  end

  def fix_spelling_grammar
    call_llm_with_prompt(prompt_from_file('fix_spelling_grammar'))
  end

  def improve
    template = prompt_from_file('improve')

    system_prompt = render_liquid_template(template, {
                                             'conversation_context' => conversation.to_llm_text(include_contact_details: true),
                                             'draft_message' => content
                                           })

    call_llm_with_prompt(system_prompt, content)
  end

  def call_llm_with_prompt(system_content, user_content = content)
    make_api_call(
      feature: 'editor',
      messages: [
        { role: 'system', content: system_content },
        { role: 'user', content: user_content }
      ]
    )
  end

  def render_liquid_template(template_content, variables = {})
    Liquid::Template.parse(template_content).render(variables)
  end

  def tone_rewrite_prompt(tone)
    template = prompt_from_file('tone_rewrite')
    render_liquid_template(template, 'tone' => tone)
  end

  def event_name
    operation
  end

  def use_account_openai_hook?
    true
  end
end
