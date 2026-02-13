import 'vuetify/styles'
import '@mdi/font/css/materialdesignicons.css'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

export default createVuetify({
  components,
  directives,
  theme: {
    defaultTheme: 'light',
    themes: {
      light: {
        colors: {
          primary: '#303F9F',
          'primary-darken-1': '#1A237E',
          secondary: '#455A64',
          accent: '#00BFA5',
          surface: '#FAFAFA',
          background: '#F5F5F5',
        },
      },
    },
  },
})
