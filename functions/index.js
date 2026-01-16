/**
 * Chole AI Follow-up Function
 * Allows users to ask questions about mining news articles
 * Uses Claude API for intelligent responses
 */

const functions = require('firebase-functions');
const admin = require('firebase-admin');
const Anthropic = require('@anthropic-ai/sdk');

// Initialize Firebase Admin
if (!admin.apps.length) {
  admin.initializeApp();
}

const db = admin.firestore();

// Initialize Anthropic client
const anthropic = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY || functions.config().anthropic?.api_key
});

/**
 * AI Follow-up Question Handler
 * POST /askFollowup
 * Body: { articleId, question, articleContext }
 */
exports.askFollowup = functions.https.onCall(async (data, context) => {
  try {
    const { articleId, question, articleContext } = data;
    
    if (!question || question.trim().length === 0) {
      throw new functions.https.HttpsError('invalid-argument', 'Question is required');
    }
    
    if (question.length > 500) {
      throw new functions.https.HttpsError('invalid-argument', 'Question too long (max 500 characters)');
    }
    
    // Build context from article
    const systemPrompt = `You are a senior mining industry analyst assistant for Chole, a mining news platform. 
You provide expert-level analysis and answers about mining industry news.

When answering:
- Be specific with numbers, companies, and technical details
- Provide industry context and implications
- Keep responses concise but informative (2-4 paragraphs max)
- If you don't know something, say so rather than speculating
- Reference specific data points from the article when relevant`;

    const userPrompt = `Article Context:
Headline: ${articleContext.headline}
Source: ${articleContext.source}
Summary: ${articleContext.summary}
Key Points:
${articleContext.bullets?.map(b => `- ${b.text}`).join('\n') || 'No bullet points available'}

User Question: ${question}

Please provide a helpful, expert-level response to this question about the mining news article.`;

    // Call Claude API
    const message = await anthropic.messages.create({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 1024,
      messages: [
        {
          role: 'user',
          content: userPrompt
        }
      ],
      system: systemPrompt
    });
    
    const response = message.content[0].text;
    
    // Log the interaction (optional - for analytics)
    await db.collection('ai_interactions').add({
      articleId,
      question,
      responseLength: response.length,
      timestamp: admin.firestore.FieldValue.serverTimestamp(),
      userId: context.auth?.uid || 'anonymous'
    });
    
    return {
      success: true,
      response: response
    };
    
  } catch (error) {
    console.error('AI Follow-up Error:', error);
    
    if (error instanceof functions.https.HttpsError) {
      throw error;
    }
    
    throw new functions.https.HttpsError('internal', 'Failed to generate response');
  }
});

/**
 * Health check endpoint
 */
exports.healthCheck = functions.https.onRequest((req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});
