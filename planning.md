## Detection Signals
    1. LLM based detection: Use a pre-trained language model to analyze the text and identify patterns indicative of AI-generated content. This can include checking for unnatural phrasing, lack of context, or inconsistencies in style.
    2: Style analysis: Compare the writing style of the content in question with known human writing styles. Examine 2 factors, the varience of sentence length. Humans usually write sentences varying in length, while AI-generated content may have more uniform sentence lengths. The seconnd factor is Punctuation usage. Humans tend to use punctuation more variably, while AI-generated content may have more consistent punctuation patterns (using lots of em dashes, colons, and semicolons).

## Uncertainty representation
    1. Confidence scores: Assign a confidence score to each detection signal, indicating the likelihood that the content is AI-generated. This can be based on the output of the LLM analysis and style comparison.
    2. Aggregated uncertainty: Combine the confidence scores from multiple detection signals to provide an overall uncertainty representation. I will do this by using a weighted average of the confidence scores, with weights determined by the reliability of each detection signal.

## Transparency Label Design
    High Confidence AI Label: AI-generated (High Confidence)

    High-Confidence Human Label: Human-written (High Confidence)

    Uncertain Label: We are unncertain if this content is AI-generated or human-written. The content may be a mix of both.

## Appeals Flow
    Users can submit an appeal if they think the AI detection is incorrect, specifically if the content is labeled as AI-generated or uncertain. The appeal process will involve a human reviewer who will assess the content and make a final determination. The reviewer will have access to the both a breakdown of both signals and the aggregated uncertainty representation to inform their decision.

## Edge Cases
    The system will most likely be iffy for peices of text that are dually written by humans and AI. For example, if a human writes a paragraph and then uses an AI tool to expand on it, the system may have difficulty determining the origin of the content. In these cases, the system will label the content as uncertain and provide an option for users to submit an appeal for human review.

## Architecture
    For the architecture, I will use a microservices approach. The system will consist of several independent services that communicate with each other through APIs. The flow will be: POST /submit -> LLM Analysis Service -> Style Analysis Service -> Aggregation Service -> Labeling Service. Each service will be responsible for a specific task, and the system will be designed to be scalable and fault-tolerant. As for the appeal flow, POST /appeal -> append to a queue -> Human Review Service -> Final Decision Service. The human review service will be responsible for reviewing the content and making a final determination, while the final decision service will update the label and notify the user of the outcome.

    (Implementation note: this ended up as a single Flask process calling plain
    Python functions instead of separate networked services -- see README.md
    "Spec reflection" for why. The data flow below is unchanged either way.)

    ```
    SUBMISSION FLOW
    ----------------
    creator (browser)
        |  POST /submit {text, creator_id}
        v
    [Flask /submit route] --------------------------------------------+
        |  raw text                     |  raw text                   |
        v                                v                             |
    [llm_signal()]                 [stylometric_signal()]              |
    Groq LLM judgment              sentence-length variance +          |
    -> llm_score (0-1)             punctuation density                 |
        |                          -> style_score (0-1)                |
        |  llm_score                    |  style_score                 |
        +---------------+---------------+                              |
                        v                                              |
                [combine_scores()]                                     |
                weighted avg -> combined_score                         |
                -> confidence, attribution, label text                 |
                        |                                               |
                        v                                               |
                [audit log: log_event()]  <----------------------------+
                        |
                        v
                response to creator: {content_id, attribution,
                confidence, label, signal breakdown}

    APPEAL FLOW
    -----------
    creator (browser)
        |  POST /appeal {content_id, creator_reasoning}
        v
    [Flask /appeal route] -> submission.status = "under_review"
        |                     submission.appeal_reasoning = reasoning
        v
    [audit log: log_event("appeal")]
        |
        v
    GET /queue  (submissions with status == under_review)
        |
        v
    [reviewer UI: GET /review] -- human picks final attribution -->
        |
        v
    POST /review/<content_id>/decision {reviewer_attribution, reviewer_notes}
        |  overwrites attribution/label, status -> "resolved"
        v
    [audit log: log_event("review_decision")]
    ```

## AI Tool Plan
    M3: I will give the AI my explanation of my submission endpoint + my first signal(LLM analysis) section and ask it to generate a Flask app skeleton with a place for a user to submit text aswell as a log of previous submits from that session. I will ask it to generate the first post endpoint for the LLM analysis service, which will take the submitted text and return a confidence score indicating the likelihood that the content is AI-generated. 

    M4: I will give the AI my explanation of my second signal(style analysis) section and ask it to generate a post endpoint for the style analysis service, which will take the submitted text and return a confidence score indicating the likelihood that the content is AI-generated based on style analysis.

    M5: I will give the AI my explanation of my aggregation section and ask it to generate a post endpoint for the aggregation service, which will take the confidence scores from the LLM analysis and style analysis services and return an overall confidence score indicating the likelihood that the content is AI-generated. On top of that, if the result is uncertain or high confidence AI, I will add a button for appeal in which the AI will generate a post endpoint for the appeal service, which will take the submitted text and send it to a human reviewer for assessment. The human reviewer will have access to the breakdown of both signals and the aggregated uncertainty representation to inform their decision. The final decision service will update the label and then notify the user of the outcome.