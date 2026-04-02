/**
 * Quick test: Can we connect to Azure Speech Service?
 * Tests both ConversationTranscriber and SpeechRecognizer.
 */
import * as sdk from "microsoft-cognitiveservices-speech-sdk";

const speechKey = process.env.AZURE_SPEECH_KEY || "";
const speechRegion = process.env.AZURE_SPEECH_REGION || "";

if (!speechKey || !speechRegion) {
  console.error("Set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION");
  process.exit(1);
}

console.log(`Testing Azure Speech SDK...`);
console.log(`  Region: ${speechRegion}`);
console.log(`  Key: ${speechKey.slice(0, 8)}...${speechKey.slice(-4)}`);

const speechConfig = sdk.SpeechConfig.fromSubscription(speechKey, speechRegion);
speechConfig.speechRecognitionLanguage = "en-US";

// Create a push stream and send a short silence burst to trigger connection
const pushStream = sdk.AudioInputStream.createPushStream(
  sdk.AudioStreamFormat.getWaveFormatPCM(16000, 16, 1)
);
const audioConfig = sdk.AudioConfig.fromStreamInput(pushStream);

// Send 1 second of silence (just to establish the connection)
const silence = new Int16Array(16000); // 1s at 16kHz
pushStream.write(silence.buffer);

// Test 1: ConversationTranscriber
console.log("\n--- Test 1: ConversationTranscriber ---");
try {
  const transcriber = new sdk.ConversationTranscriber(speechConfig, audioConfig);

  transcriber.transcribed = (_s: any, e: any) => {
    console.log(`  [transcribed] "${e.result.text}" speaker=${e.result.speakerId}`);
  };
  transcriber.transcribing = (_s: any, e: any) => {
    console.log(`  [transcribing] "${e.result.text}"`);
  };
  transcriber.canceled = (_s: any, e: any) => {
    const details = e.errorDetails || e.reason || "";
    console.error(`  [canceled] ${details}`);
  };
  transcriber.sessionStarted = () => {
    console.log(`  [sessionStarted] Connection established!`);
  };
  transcriber.sessionStopped = () => {
    console.log(`  [sessionStopped]`);
  };

  await new Promise<void>((resolve, reject) => {
    transcriber.startTranscribingAsync(
      () => {
        console.log("  ConversationTranscriber started successfully!");
        resolve();
      },
      (err: string) => {
        console.error(`  ConversationTranscriber start failed: ${err}`);
        reject(new Error(err));
      }
    );
  });

  // Keep alive for 5 seconds to see if we get session events
  console.log("  Waiting 5s for session events...");
  await new Promise((r) => setTimeout(r, 5000));

  await new Promise<void>((resolve) => {
    transcriber.stopTranscribingAsync(
      () => { console.log("  Stopped."); resolve(); },
      () => resolve()
    );
  });
} catch (err: any) {
  console.error(`  ConversationTranscriber test failed: ${err.message}`);
}

// Test 2: SpeechRecognizer (separate stream needed)
console.log("\n--- Test 2: SpeechRecognizer ---");
try {
  const pushStream2 = sdk.AudioInputStream.createPushStream(
    sdk.AudioStreamFormat.getWaveFormatPCM(16000, 16, 1)
  );
  const audioConfig2 = sdk.AudioConfig.fromStreamInput(pushStream2);
  pushStream2.write(silence.buffer);

  const recognizer = new sdk.SpeechRecognizer(speechConfig, audioConfig2);

  recognizer.recognized = (_s: any, e: any) => {
    if (e.result.reason === sdk.ResultReason.RecognizedSpeech) {
      console.log(`  [recognized] "${e.result.text}"`);
    } else if (e.result.reason === sdk.ResultReason.NoMatch) {
      console.log(`  [no match] — silence detected (expected)`);
    }
  };
  recognizer.recognizing = (_s: any, e: any) => {
    console.log(`  [recognizing] "${e.result.text}"`);
  };
  recognizer.canceled = (_s: any, e: any) => {
    const details = e.errorDetails || e.reason || "";
    console.error(`  [canceled] ${details}`);
  };
  recognizer.sessionStarted = () => {
    console.log(`  [sessionStarted] Connection established!`);
  };

  await new Promise<void>((resolve, reject) => {
    recognizer.startContinuousRecognitionAsync(
      () => {
        console.log("  SpeechRecognizer started successfully!");
        resolve();
      },
      (err: string) => {
        console.error(`  SpeechRecognizer start failed: ${err}`);
        reject(new Error(err));
      }
    );
  });

  console.log("  Waiting 5s for session events...");
  await new Promise((r) => setTimeout(r, 5000));

  await new Promise<void>((resolve) => {
    recognizer.stopContinuousRecognitionAsync(
      () => { console.log("  Stopped."); resolve(); },
      () => resolve()
    );
  });
  pushStream2.close();
} catch (err: any) {
  console.error(`  SpeechRecognizer test failed: ${err.message}`);
}

pushStream.close();
console.log("\n--- Done ---");
process.exit(0);
